#!/usr/bin/env python3
"""Collect real Jev scores for explicitly labeled question-level cases.

Run from the repository root with TYPESAFE_API_KEY set:
  python3 tools/collect_decision_scores.py tests/data/decision_cases.json /tmp/jev-scores.jsonl
The output contains no API key. It may contain case names and should still be treated
as local evaluation data. Repeats measure Jev variation, not independent cases.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
hook = runpy.run_path(str(ROOT / "jev-no-bullshit"))


def collect(cases: list[dict], key: str, repeats: int) -> list[dict]:
    records = []
    for case in cases:
        state, _ = hook["build_state"](
            case["task"], case["actions"], case["summary"], hook["state_token_budget"](),
            case.get("earlier_actions", []), case.get("conversation", []),
        )
        questions, _, _ = hook["build_questions"](state)
        composed_ids = {qid.replace("unverified_action_", "unverified_", 1)
                        for qid in questions if qid.startswith("unverified_action_s")}
        unknown = set(case["labels"]) - (set(questions) | composed_ids)
        if unknown:
            raise ValueError(f"{case['id']}: labels name missing questions: {sorted(unknown)}")
        if not case["labels"]:
            raise ValueError(f"{case['id']}: no labels")
        for run in range(repeats):
            response = hook["ask_jev"](state, questions, key, time.monotonic() + 60)
            scores = hook["noul_values"](response)
            scores.update(hook["compose_unverified"](scores, questions))
            for question_id, label in case["labels"].items():
                if question_id not in scores:
                    raise ValueError(f"{case['id']}: Jev omitted {question_id}")
                records.append({
                    "case_id": f"{case['id']}/{question_id}",
                    "session_id": case["session_id"],
                    "type": question_id.rsplit("_", 1)[0],
                    "label": label,
                    "score": scores[question_id],
                    "model": response["model"],
                    "run": run,
                })
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        parser.error("TYPESAFE_API_KEY is not set")
    cases = json.loads(args.cases.read_text())
    records = collect(cases, api_key, args.repeats)
    args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records))
    print(f"wrote {len(records)} labeled scores from {len(cases)} cases to {args.output}")
