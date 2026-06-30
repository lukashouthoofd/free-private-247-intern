"""Usage log + spend cap tests — stdlib only, no network, no creds.
   Each test points USAGE_DIR at a fresh tempdir so the real data/ is never touched."""
import os
import tempfile
import unittest

from agent import usage


class TestUsage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("USAGE_DIR")
        os.environ["USAGE_DIR"] = self.tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("USAGE_DIR", None)
        else:
            os.environ["USAGE_DIR"] = self._prev

    def test_missing_file_never_crashes(self):
        # nothing written yet — sums must return 0, not raise
        self.assertEqual(usage.today_calls(), 0)
        self.assertEqual(usage.today_spend_usd(), 0.0)

    def test_record_and_sum_roundtrip(self):
        # OpenAI-shape usage with an explicit cost
        usage.record("openai", "gpt-4o-mini",
                     {"prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.002})
        # Anthropic-shape usage, no cost field -> counts as a call, 0 spend
        usage.record("anthropic", "claude-3", {"input_tokens": 10, "output_tokens": 20})
        # claude-code shape: total_cost_usd
        usage.record("claude-code", "sonnet", {"total_cost_usd": 0.01})

        self.assertEqual(usage.today_calls(), 3)
        self.assertAlmostEqual(usage.today_spend_usd(), 0.012, places=6)

    def test_record_returns_normalized_record(self):
        rec = usage.record("openai", "m", {"prompt_tokens": 7, "completion_tokens": 3, "cost_usd": 0.5})
        self.assertEqual(rec["input_tokens"], 7)
        self.assertEqual(rec["output_tokens"], 3)
        self.assertEqual(rec["cost_usd"], 0.5)
        self.assertEqual(rec["provider"], "openai")

    def test_empty_and_none_usage_are_safe(self):
        usage.record("ollama", "qwen2.5:3b", {})     # empty dict (local, no usage)
        usage.record("ollama", "qwen2.5:3b", None)   # None usage
        self.assertEqual(usage.today_calls(), 2)
        self.assertEqual(usage.today_spend_usd(), 0.0)

    def test_corrupt_lines_are_skipped(self):
        usage.record("openai", "m", {"cost_usd": 0.005})
        with open(os.path.join(self.tmp, "usage.jsonl"), "a", encoding="utf-8") as f:
            f.write("not json at all\n\n")
        # the good line still counts; garbage is ignored
        self.assertEqual(usage.today_calls(), 1)
        self.assertAlmostEqual(usage.today_spend_usd(), 0.005, places=6)

    def test_over_cap_call_under_and_over(self):
        cfg = {"agent": {"daily_call_cap": 2}}
        over, reason = usage.over_cap(cfg)
        self.assertFalse(over)
        usage.record("openai", "m", {})
        usage.record("openai", "m", {})
        over, reason = usage.over_cap(cfg)
        self.assertTrue(over)
        self.assertIn("call cap", reason)

    def test_over_cap_usd_under_and_over(self):
        cfg = {"agent": {"daily_usd_cap": 0.01}}
        usage.record("openai", "m", {"cost_usd": 0.004})
        self.assertFalse(usage.over_cap(cfg)[0])
        usage.record("openai", "m", {"cost_usd": 0.006})   # total 0.010 -> hits cap (>=)
        over, reason = usage.over_cap(cfg)
        self.assertTrue(over)
        self.assertIn("USD cap", reason)

    def test_zero_or_absent_cap_is_unlimited(self):
        for _ in range(5):
            usage.record("openai", "m", {"cost_usd": 9.99})
        self.assertFalse(usage.over_cap({"agent": {"daily_call_cap": 0, "daily_usd_cap": 0}})[0])
        self.assertFalse(usage.over_cap({"agent": {}})[0])
        self.assertFalse(usage.over_cap({})[0])

    def test_usage_summary_tool_gate_autonomous(self):
        names = {t.name: t.gate for t in usage.USAGE_TOOLS}
        self.assertEqual(names["usage_summary"], "autonomous")

    def test_usage_summary_tool_output(self):
        usage.record("openai", "m", {"cost_usd": 0.003})
        out = usage.USAGE_TOOLS[0].fn({})
        self.assertIn("1 call", out)
        self.assertIn("0.003", out)


if __name__ == "__main__":
    unittest.main()
