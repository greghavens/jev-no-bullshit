#!/usr/bin/env python3
"""Replay logged checks through the hook script in this repository.

Run from the repository root with JEV_API_KEY set (or ~/.config/jev-no-bullshit/harness.env):
  python3 tools/replay.py [--hook PATH] [--tool claude|codex] [--since ISO] [--at TIME ...]
                          [--unflagged-sample N [--seed S]] [--limit N] [--out PATH]
By default it replays every logged check that flagged something. --since keeps checks at or after an
ISO time; --at picks the checks whose logged time starts with TIME, flagged or not (repeatable);
--unflagged-sample adds N checks, chosen with --seed, that flagged nothing, to look for new flags.
Each check is rebuilt from its Claude Code or Codex transcript as it stood at the check. A check the
hook would not send (its redirects used up, or nothing to ask) is reported as skipped; the rest are
sent to Jev once. Responses are cached by request hash in ~/.jev-no-bullshit/replay/cache, so an
unchanged request is never asked again. Results go to --out, or ~/.jev-no-bullshit/replay/<hook>-<time>.jsonl:
one line per check with the flags then (logged) and now, the tokens billed then and now, and the
number of questions asked.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import runpy
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path.home() / ".jev-no-bullshit" / "log.jsonl"
OUT = Path.home() / ".jev-no-bullshit" / "replay"
CACHE = OUT / "cache"


def logged_checks(tool: str | None, since: str | None) -> list[dict]:
    """The checks Jev answered, oldest first."""
    out = []
    for line in LOG.open():
        if not line.strip():
            continue
        d = json.loads(line)
        if not (d.get("answers") and d.get("summary")):
            continue
        if tool is not None and d.get("tool", "claude") != tool:
            continue
        if since and d.get("time", "") < since:
            continue
        out.append(d)
    return out


def flagged(d: dict) -> bool:
    return any((d.get("flagged") or {}).values())


def select(checks: list[dict], at: list[str], sample: int, seed: int) -> list[dict]:
    """The flagged checks, or those --at names; plus a seeded sample of unflagged ones."""
    chosen = [d for d in checks if any(d.get("time", "").startswith(t) for t in at)] if at else [d for d in checks if flagged(d)]
    if sample:
        pool = [d for d in checks if not flagged(d) and d not in chosen]
        chosen += random.Random(seed).sample(pool, min(sample, len(pool)))
    return sorted(chosen, key=lambda d: d.get("time", ""))


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


def request(h: dict, task, actions, summary, earlier, conversation) -> tuple[dict, dict]:
    """(state as sent, questions) as the hook builds them; an older hook (v0.4) is supported too."""
    if "wire_state" in h:
        state, _ = h["build_state"](task, actions, summary, earlier, conversation)
        questions, _, _ = h["build_questions"](state, summary)
        return h["wire_state"](state), questions
    state, _ = h["build_state"](task, actions, summary, h["state_token_budget"](), earlier, conversation)
    questions, _, _ = h["build_questions"](state)
    return state, questions


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
            # As run() does since v0.5: flags after the last redirect could only be logged, so they are not asked.
            if "wire_state" in h and d.get("attempt", 0) >= h["max_redirects"]():
                reqs.append({"check": d, "skipped": "redirects used up"})
                continue
            codex = d.get("tool") == "codex"
            es = cut_entries(entries, d)
            task, actions, _, earlier = (h["parse_codex"] if codex else h["parse_claude"])(es)
            conversation = (h["conversation_codex"] if codex else h["conversation_claude"])(es, d["summary"])
            state, questions = request(h, task, actions, d["summary"], earlier, conversation)
            if not questions:
                reqs.append({"check": d, "skipped": "nothing to check"})
                continue
            estimated = h["REQUEST_OVERHEAD_TOKENS"] + h["estimate_tokens"](state) + sum(map(h["question_tokens"], questions.values()))
            digest = hashlib.sha256(json.dumps([state, questions]).encode()).hexdigest()[:24]
            reqs.append({"check": d, "state": state, "questions": questions, "hash": digest, "estimated_tokens": round(estimated)})
    return reqs


def ask(h: dict, key: str, req: dict) -> dict:
    """One Jev call per distinct request; a cached response is reused, never asked again."""
    path = CACHE / f"{req['hash']}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        # Older cache files hold the answers alone.
        return cached if "answers" in cached else {"answers": cached}
    try:
        response = h["ask_jev"](req["state"], req["questions"], key, time.monotonic() + 120)
        result = {"answers": h["noul_values"](response), "usage": response.get("usage"), "jev_model": response.get("model")}
    except Exception as error:  # noqa: BLE001 - reported per check, not fatal to the run
        return {"error": f"{type(error).__name__}: {error}"}
    path.write_text(json.dumps(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hook", type=Path, default=ROOT / "jev-no-bullshit")
    parser.add_argument("--tool", choices=["claude", "codex"])
    parser.add_argument("--since", help="only checks logged at or after this ISO time, e.g. 2026-09-26")
    parser.add_argument("--at", action="append", default=[], metavar="TIME",
                        help="the checks whose logged time starts with TIME, flagged or not (repeatable)")
    parser.add_argument("--unflagged-sample", type=int, default=0, metavar="N", help="also replay N checks that flagged nothing")
    parser.add_argument("--seed", type=int, default=0, help="seed for --unflagged-sample")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--out", type=Path, help="where to write the results (JSON lines)")
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
    checks = select(logged_checks(args.tool, args.since), args.at, args.unflagged_sample, args.seed)[: args.limit]
    reqs = build(h, checks)
    print(f"{len(checks)} checks; {sum('missing' in r for r in reqs)} without a transcript, "
          f"{sum('skipped' in r for r in reqs)} the hook would not send", flush=True)

    ready = [r for r in reqs if "hash" in r]
    unique = {r["hash"]: r for r in ready}
    with ThreadPoolExecutor(args.threads) as pool:
        answers = dict(zip(unique, pool.map(lambda r: ask(h, key, r), unique.values())))

    thresholds = {t: h["threshold"](t) for t in h["TYPES"]}
    out = args.out or OUT / f"{args.hook.name}-{time.strftime('%Y%m%dT%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    totals = {"checks": len(checks), "flagged_then": 0, "flagged_now": 0, "skipped": 0, "errors": 0, "missing": 0}
    # Billed input per check, then and now, over the same checks: those billed then and either billed
    # now or skipped now (0). A check that errored or is missing now, or had no usage then, is in neither.
    billed = {"then": [], "now": []}
    with out.open("w") as f:
        for r in reqs:
            d = r["check"]
            usage_then = d.get("usage") or {}
            row = {"time": d["time"], "session_id": d["session_id"], "tool": d.get("tool", "claude"), "attempt": d.get("attempt", 0),
                   "flagged_then": d.get("flagged") or {}, "usage_then": usage_then, "questions_then": len(d.get("answers") or {}),
                   "summary": d["summary"]}
            totals["flagged_then"] += flagged(d)
            now_tokens = None
            if "missing" in r:
                totals["missing"] += 1
                row["missing"] = r["missing"]
            elif "skipped" in r:
                totals["skipped"] += 1
                row.update(skipped=r["skipped"], flagged_now={}, usage_now={"input_tokens": 0}, questions_now=0)
                now_tokens = 0
            elif "error" in answers[r["hash"]]:
                totals["errors"] += 1
                row["error"] = answers[r["hash"]]["error"]
            else:
                response = answers[r["hash"]]
                values = dict(response["answers"])
                values.update(h["compose"](values, r["questions"]))
                now = h["find_flags"](values, thresholds)
                row.update(flagged_now=now, scores_now={q: values[q] for qs in now.values() for q in qs},
                           usage_now=response.get("usage"), estimated_tokens_now=r["estimated_tokens"],
                           questions_now=len(r["questions"]), sentences=r["state"].get("sentences"))
                now_tokens = (response.get("usage") or {}).get("input_tokens")
                totals["flagged_now"] += any(now.values())
            if usage_then.get("input_tokens") and now_tokens is not None:
                billed["then"].append(usage_then["input_tokens"])
                billed["now"].append(now_tokens)
            f.write(json.dumps(row) + "\n")
    mean = {k: round(sum(v) / len(v)) if v else None for k, v in billed.items()}
    print(json.dumps({**totals, "mean_input_tokens": mean, "mean_input_checks": len(billed["now"]), "thresholds": thresholds, "results": str(out)}, indent=1))


if __name__ == "__main__":
    main()
