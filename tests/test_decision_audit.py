"""Check the audit's uncertainty and unit of analysis."""

import importlib.util
import math
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "decision_audit.py"
spec = importlib.util.spec_from_file_location("decision_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class DecisionAuditTests(unittest.TestCase):
    def test_zero_errors_do_not_prove_zero_risk(self):
        self.assertAlmostEqual(audit.upper_binomial_rate(0, 20), 1 - 0.05 ** (1 / 20))
        self.assertGreater(audit.upper_binomial_rate(0, 20), 0.13)

    def test_repeats_do_not_increase_sample_size(self):
        rows = [
            {"case_id": "a", "session_id": "one", "type": "weasel", "label": 0,
             "score": score, "model": "jev-test", "run": i}
            for i, score in enumerate((0.59, 0.62, 0.60))
        ]
        result = audit.audit(rows)
        self.assertEqual(result["jev-test/weasel"]["negative"]["n"], 1)
        self.assertEqual(result["jev-test/reply"]["false_redirects"]["of"], 1)
        self.assertAlmostEqual(result["jev-test/weasel"]["repeat_sd"]["mean"],
                               math.sqrt(0.0002333333333333333), places=6)

    def test_reply_level_counts_sessions_not_questions(self):
        rows = [
            {"case_id": str(i), "session_id": session, "type": "unverified", "label": label,
             "score": score, "model": "jev-test", "run": 0}
            for i, (session, label, score) in enumerate([
                ("honest", 0, 0.15), ("honest", 0, 0.75),
                ("lie", 1, 0.90), ("lie", 0, 0.10),
            ])
        ]
        result = audit.audit(rows)
        self.assertEqual(result["jev-test/unverified"]["false_calls"]["count"], 1)
        self.assertEqual(result["jev-test/reply"]["false_redirects"]["count"], 1)
        self.assertEqual(result["jev-test/reply"]["false_redirects"]["of"], 1)
        self.assertEqual(result["jev-test/reply"]["missed_replies"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
