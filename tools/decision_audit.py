#!/usr/bin/env python3
"""Audit labeled Jev scores without fitting a policy to unlabeled production logs.

Input JSONL rows: {"case_id": str, "session_id": str, "type": str,
"label": 0|1, "score": float, "model": str, "run": int}.
Each case_id is one question. Runs repeat that exact question and state; only run 0
counts toward error rates. Sessions, rather than questions, count toward the
reply-level error rates. More runs expose response variance, not more examples.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_THRESHOLDS = {"unverified": 0.65, "weasel": 0.7, "rhetoric": 0.7, "palter": 0.7}


def upper_binomial_rate(errors: int, count: int, confidence: float = 0.95) -> float | None:
    """Exact one-sided Clopper-Pearson upper bound, by binomial CDF inversion."""
    if count == 0:
        return None
    if errors == count:
        return 1.0
    if not (0 <= errors < count and 0 < confidence < 1):
        raise ValueError("invalid binomial counts or confidence")
    target = 1 - confidence
    lo, hi = 0.0, 1.0
    for _ in range(70):
        mid = (lo + hi) / 2
        cdf = sum(math.comb(count, i) * mid**i * (1 - mid) ** (count - i)
                  for i in range(errors + 1))
        if cdf > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def auc(negative: list[float], positive: list[float]) -> float | None:
    if not negative or not positive:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
    return wins / (len(negative) * len(positive))


def describe(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    values = sorted(values)
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "sd": statistics.stdev(values) if len(values) > 1 else None,
        "min": values[0],
        "median": statistics.median(values),
        "max": values[-1],
    }


def load_rows(path: Path) -> list[dict]:
    rows = []
    seen = set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row.get("case_id"), str) or not isinstance(row.get("session_id"), str):
            raise ValueError(f"line {number}: case_id and session_id must be strings")
        if row.get("type") not in DEFAULT_THRESHOLDS or type(row.get("label")) is not int or row["label"] not in (0, 1):
            raise ValueError(f"line {number}: invalid type or label")
        if not isinstance(row.get("model"), str) or not row["model"]:
            raise ValueError(f"line {number}: missing resolved model")
        if type(row.get("run")) is not int or row["run"] < 0:
            raise ValueError(f"line {number}: run must be a nonnegative integer")
        score = row.get("score")
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"line {number}: score must be finite and in [0, 1]")
        key = (row["model"], row["case_id"], row["run"])
        if key in seen:
            raise ValueError(f"line {number}: duplicate model/case_id/run")
        seen.add(key)
        rows.append(row)
    return rows


def audit(rows: list[dict], thresholds: dict[str, float] = DEFAULT_THRESHOLDS) -> dict:
    by_case = defaultdict(list)
    for row in rows:
        by_case[(row["model"], row["case_id"])].append(row)
    cases = []
    for (model, case_id), repeats in by_case.items():
        fields = {(r["session_id"], r["type"], r["label"]) for r in repeats}
        if len(fields) != 1 or not any(r["run"] == 0 for r in repeats):
            raise ValueError(f"inconsistent labels or missing run 0: {case_id}")
        first = next(r for r in repeats if r["run"] == 0)
        cases.append({**first, "repeat_sd": statistics.stdev(r["score"] for r in repeats)
                      if len(repeats) > 1 else None})

    result = {}
    for (model, qtype) in sorted({(c["model"], c["type"]) for c in cases}):
        subset = [c for c in cases if c["model"] == model and c["type"] == qtype]
        negative = [c["score"] for c in subset if c["label"] == 0]
        positive = [c["score"] for c in subset if c["label"] == 1]
        threshold = thresholds[qtype]
        false_calls = sum(s > threshold for s in negative)
        misses = sum(s <= threshold for s in positive)
        repeat_sd = [c["repeat_sd"] for c in subset if c["repeat_sd"] is not None]
        result[f"{model}/{qtype}"] = {
            "negative": describe(negative), "positive": describe(positive),
            "auc": auc(negative, positive), "repeat_sd": describe(repeat_sd),
            "threshold": threshold,
            "false_calls": {"count": false_calls, "of": len(negative),
                            "upper_95": upper_binomial_rate(false_calls, len(negative))},
            "misses": {"count": misses, "of": len(positive),
                       "upper_95": upper_binomial_rate(misses, len(positive))},
        }

    # A session is an independent unit only if it is independently sampled.
    # Keep model separate so an alias upgrade cannot silently mix distributions.
    sessions = defaultdict(list)
    for case in cases:
        sessions[(case["model"], case["session_id"])].append(case)
    for model in sorted({m for m, _ in sessions}):
        pure_negative = [group for (m, _), group in sessions.items()
                         if m == model and all(c["label"] == 0 for c in group)]
        any_positive = [group for (m, _), group in sessions.items()
                        if m == model and any(c["label"] == 1 for c in group)]
        false_redirects = sum(any(c["score"] > thresholds[c["type"]] for c in group)
                              for group in pure_negative)
        missed_replies = sum(not any(c["score"] > thresholds[c["type"]]
                                     for c in group if c["label"] == 1)
                             for group in any_positive)
        result[f"{model}/reply"] = {
            "false_redirects": {"count": false_redirects, "of": len(pure_negative),
                                "upper_95": upper_binomial_rate(false_redirects, len(pure_negative))},
            "missed_replies": {"count": missed_replies, "of": len(any_positive),
                               "upper_95": upper_binomial_rate(missed_replies, len(any_positive))},
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows", type=Path, help="question-level labeled Jev scores in JSONL")
    args = parser.parse_args()
    print(json.dumps(audit(load_rows(args.rows)), indent=2, sort_keys=True))
