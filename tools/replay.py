#!/usr/bin/env python3
"""Replay every logged check that flagged something through the hook script in this repository.

Run from the repository root with JEV_API_KEY set (or ~/.config/jev-no-bullshit/harness.env):
  python3 tools/replay.py [--hook PATH] [--tool claude|codex] [--limit N]
Each check is rebuilt from its Claude Code or Codex transcript as it stood at the check, then sent
to Jev once. Answers are cached by request hash in ~/.jev-no-bullshit/replay/cache, so an unchanged
request is never asked again. Results go to ~/.jev-no-bullshit/replay/<hook>-<time>.jsonl: one line
per check with the sentences and actions flagged then and now, for review.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import runpy
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path.home() / ".jev-no-bullshit" / "log.jsonl"
OUT = Path.home() / ".jev-no-bullshit" / "replay"
CACHE = OUT / "cache"


def flagged_checks(tool: str | None) -> list[dict]:
    out = []
    for line in LOG.open():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("answers") and d.get("summary") and any((d.get("flagged") or {}).values()):
            if tool is None or d.get("tool", "claude") == tool:
                out.append(d)
    return out


def transcript_path(d: dict) -> str | None:
    sid = d["session_id"]
    if d.get("tool") == "codex":
        found = glob.glob(os.path.expanduser(f"~/.codex/sessions/**/*{sid}*.jsonl"), recursive=True)
    else:
        found = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
    return found[0] if found else None


def text_of(e: dict) -> str:
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return c if isinstance(c, str) else ""


def cut_entries(entries: list[dict], d: dict) -> list[dict]:
    """The transcript as it stood at the check: up to the entry holding the summary, else by time."""
    want = d["summary"].strip()
    if d.get("tool", "claude") == "claude":
        for i, e in enumerate(entries):
            if e.get("type") == "assistant" and text_of(e).strip() == want:
                return entries[: i + 1]
    cut = d["time"][:19]
    return [e for e in entries if (e.get("timestamp") or "")[:19] <= cut]


def build(h: dict, checks: list[dict]) -> list[dict]:
    by_session: dict[str, list[dict]] = {}
    for d in checks:
        by_session.setdefault(d["session_id"], []).append(d)
    reqs = []
    for ds in by_session.values():
        path = transcript_path(ds[0])
        if not path:
            reqs += [{"check": d, "missing": "transcript not found"} for d in ds]
            continue
        entries = h["read_jsonl"](path)
        for d in ds:
            codex = d.get("tool") == "codex"
            es = cut_entries(entries, d)
            task, actions, _, earlier = (h["parse_codex"] if codex else h["parse_claude"])(es)
            conversation = (h["conversation_codex"] if codex else h["conversation_claude"])(es, d["summary"])
            state, _ = h["build_state"](task, actions, d["summary"], h["state_token_budget"](), earlier, conversation)
            questions, _, _ = h["build_questions"](state)
            digest = hashlib.sha256(json.dumps([state, questions]).encode()).hexdigest()[:24]
            reqs.append({"check": d, "state": state, "questions": questions, "hash": digest})
    return reqs


def ask(h: dict, key: str, req: dict) -> dict:
    """One Jev call per distinct request; a cached answer is reused, never asked again."""
    path = CACHE / f"{req['hash']}.json"
    if path.exists():
        return json.loads(path.read_text())
    try:
        values = h["noul_values"](h["ask_jev"](req["state"], req["questions"], key, time.monotonic() + 120))
    except Exception as error:  # noqa: BLE001 - reported per check, not fatal to the run
        return {"error": f"{type(error).__name__}: {error}"}
    path.write_text(json.dumps(values))
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hook", type=Path, default=ROOT / "jev-no-bullshit")
    parser.add_argument("--tool", choices=["claude", "codex"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()

    h = runpy.run_path(str(args.hook))
    try:
        key = h["harness_api_key"]()
    except ValueError as refused:
        parser.error(str(refused))
    if not key:
        parser.error(f"JEV_API_KEY is not set in the environment or in {h['harness_key_file']()}")
    CACHE.mkdir(parents=True, exist_ok=True)
    checks = flagged_checks(args.tool)[: args.limit]
    reqs = build(h, checks)
    print(f"{len(checks)} previously flagged checks; {sum('missing' in r for r in reqs)} without a transcript", flush=True)

    ready = [r for r in reqs if "missing" not in r]
    unique = {r["hash"]: r for r in ready}
    with ThreadPoolExecutor(args.threads) as pool:
        answers = dict(zip(unique, pool.map(lambda r: ask(h, key, r), unique.values())))

    thresholds = {t: h["threshold"](t) for t in h["TYPES"]}
    out = OUT / f"{args.hook.name}-{time.strftime('%Y%m%dT%H%M%S')}.jsonl"
    totals = {"checks": len(checks), "still_flagged": 0, "cleared": 0, "errors": 0, "missing": 0}
    with out.open("w") as f:
        for r in reqs:
            d = r["check"]
            row = {"time": d["time"], "session_id": d["session_id"], "tool": d.get("tool", "claude"),
                   "flagged_then": d["flagged"], "summary": d["summary"]}
            if "missing" in r:
                totals["missing"] += 1
                row["missing"] = r["missing"]
            elif "error" in answers[r["hash"]]:
                totals["errors"] += 1
                row["error"] = answers[r["hash"]]["error"]
            else:
                values = dict(answers[r["hash"]])
                values.update(h["compose"](values, r["questions"]))
                now = h["find_flags"](values, thresholds)
                row["flagged_now"] = now
                row["scores_now"] = {q: values[q] for qs in now.values() for q in qs}
                row["sentences"] = r["state"].get("sentences")
                totals["still_flagged" if any(now.values()) else "cleared"] += 1
            f.write(json.dumps(row) + "\n")
    print(json.dumps({**totals, "thresholds": thresholds, "results": str(out)}, indent=1))


if __name__ == "__main__":
    main()
