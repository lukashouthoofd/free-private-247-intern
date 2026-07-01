"""Hardening tests for agent.loop — run with:
    python -m unittest discover -s tests -p test_loop_hardening.py
Stdlib-only (unittest + unittest.mock), no network, no API key.

Covers issue-1 fixes:
  loop-1  : _exec fails CLOSED on an unrecognized gate label (no fall-through to running)
  loop-3  : Tool() raises at construction time on a bad gate (defense-in-depth)
  loop-4  : a tool_call with no function name yields a clear protocol error, runs nothing
  testgap-5: max_steps runaway cap actually halts the loop
  testgap-6: the daily spend cap halts BEFORE any model call is made
"""
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent import usage as usage_mod
from agent.loop import Agent, Tool


def _measure() -> Tool:
    return Tool("measure", "", {"type": "object", "properties": {}}, lambda a: "ok", "autonomous")


class TestUnknownGateFailsClosed(unittest.TestCase):
    """loop-1: a tool whose gate is neither autonomous/ask_first/never must be refused,
    not run. We bypass Tool's __post_init__ guard (loop-3) to forge a bad-gate tool, so
    this isolates the _exec defence on its own."""

    def _agent_with_bad_gate(self, gate: str) -> Agent:
        t = Tool("measure", "", {"type": "object", "properties": {}}, lambda a: "RAN", "autonomous")
        t.gate = gate  # mutate after construction to dodge the __post_init__ check
        a = Agent(configs=[], system="x", tools=[t], approver=lambda n, ar: True)
        a._tools["measure"] = t
        return a

    def test_typo_gate_is_refused_not_run(self):
        out = self._agent_with_bad_gate("autonmous")._exec("measure", {})
        self.assertIn("REFUSED", out)
        self.assertIn("unrecognized gate", out)
        self.assertNotIn("RAN", out)

    def test_empty_gate_is_refused(self):
        self.assertIn("REFUSED", self._agent_with_bad_gate("")._exec("measure", {}))

    def test_wrong_case_gate_is_refused(self):
        # 'Autonomous' != 'autonomous' -> must fail closed, not run
        out = self._agent_with_bad_gate("Autonomous")._exec("measure", {})
        self.assertIn("REFUSED", out)
        self.assertNotIn("RAN", out)

    def test_valid_gate_still_runs(self):
        # control: a genuinely autonomous tool still executes (no over-blocking)
        a = Agent(configs=[], system="x", tools=[_measure()])
        self.assertEqual(a._exec("measure", {}), "ok")


class TestToolConstructionValidation(unittest.TestCase):
    """loop-3: a bad gate must blow up loudly at construction, not at the worst moment."""

    def test_bad_gate_raises_valueerror(self):
        with self.assertRaises(ValueError):
            Tool("oops", "", {"type": "object", "properties": {}}, lambda a: "x", "definitely_not_a_gate")

    def test_empty_gate_raises(self):
        with self.assertRaises(ValueError):
            Tool("oops", "", {"type": "object", "properties": {}}, lambda a: "x", "")

    def test_error_message_names_the_tool_and_gate(self):
        with self.assertRaises(ValueError) as ctx:
            Tool("paywall", "", {"type": "object", "properties": {}}, lambda a: "x", "FULL")
        msg = str(ctx.exception)
        self.assertIn("paywall", msg)
        self.assertIn("FULL", msg)

    def test_each_valid_gate_constructs(self):
        for g in ("autonomous", "ask_first", "never"):
            Tool("t", "", {"type": "object", "properties": {}}, lambda a: "x", g)  # must not raise


class TestMissingFunctionName(unittest.TestCase):
    """loop-4: a tool_call with no name must surface a protocol error and run no tool."""

    def test_missing_name_yields_protocol_error_and_runs_nothing(self):
        ran = []
        tools = [Tool("measure", "", {"type": "object", "properties": {}},
                      lambda a: ran.append(1) or "ok", "autonomous")]
        agent = Agent(configs=[], system="x", tools=tools, max_steps=1)
        # First response: a malformed tool_call (no function name). Loop must not crash,
        # must not run a tool, and ends at max_steps.
        resp = {"tool_calls": [{"id": "1", "function": {"arguments": "{}"}}], "content": ""}
        # over_cap is imported function-locally inside run() (from .usage import over_cap),
        # so the live name to patch is agent.usage.over_cap, not agent.loop.over_cap.
        with patch("agent.loop.complete_with_fallback", return_value=resp), \
             patch("agent.usage.over_cap", return_value=(False, "")):
            out = agent.run("go")
        self.assertEqual(ran, [])              # no tool executed
        self.assertIn("max_steps", out)        # loop terminated via the cap, did not crash

    def test_missing_name_message_is_distinct_from_unknown_tool(self):
        # _exec('') would say "unknown tool ''" — loop-4 gives a clearer signal instead.
        # Verify the two are different so the model can tell a protocol error from a hallucination.
        agent = Agent(configs=[], system="x", tools=[_measure()])
        unknown = agent._exec("", {})
        self.assertIn("unknown tool", unknown)
        self.assertNotIn("protocol error", unknown)


class TestMaxStepsCap(unittest.TestCase):
    """testgap-5: the loop must stop after max_steps even if the model keeps calling tools."""

    def test_runaway_is_capped(self):
        tools = [Tool("measure", "", {"type": "object", "properties": {}}, lambda a: "ok", "autonomous")]
        agent = Agent(configs=[], system="x", tools=tools, max_steps=2,
                      approver=lambda n, a: False)
        # The model ALWAYS asks for the tool again -> would loop forever without the cap.
        resp = {"tool_calls": [{"id": "1", "function": {"name": "measure", "arguments": "{}"}}],
                "content": ""}
        # over_cap is imported function-locally inside run(); patch it at its source module.
        with patch("agent.loop.complete_with_fallback", return_value=resp) as m, \
             patch("agent.usage.over_cap", return_value=(False, "")):
            out = agent.run("go")
        self.assertIn("max_steps", out)
        self.assertEqual(m.call_count, 2)  # exactly max_steps model calls, then halt


class TestSpendCapHalt(unittest.TestCase):
    """testgap-6: when the daily call cap is already tripped, run() must halt BEFORE the
    first model call. Patch target is agent.loop.* (the names used inside run)."""

    def setUp(self):
        self._prev = os.environ.get("USAGE_DIR")
        self._dir = tempfile.mkdtemp()
        os.environ["USAGE_DIR"] = self._dir

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("USAGE_DIR", None)
        else:
            os.environ["USAGE_DIR"] = self._prev

    def test_capped_state_halts_before_any_model_call(self):
        # Record one call today so today_calls() == 1, which trips daily_call_cap=1.
        usage_mod.record("openai", "x", {"prompt_tokens": 1, "completion_tokens": 1})
        self.assertEqual(usage_mod.today_calls(), 1)

        agent = Agent(configs=[], system="x", tools=[_measure()],
                      usage_cfg={"agent": {"daily_call_cap": 1}})
        m = Mock()
        with patch("agent.loop.complete_with_fallback", m):
            out = agent.run("hello")
        self.assertIn("cap", out)
        m.assert_not_called()  # the model was never called — halted by the dead-man's-switch

    def test_usd_cap_halts_before_any_model_call(self):
        # Record a call that already cost more than the USD cap, then confirm run() halts
        # via the *dollar* branch (not just the call-count branch) before any model call.
        usage_mod.record("openai", "m", {"cost_usd": 0.02})
        self.assertGreaterEqual(usage_mod.today_spend_usd(), 0.02)

        agent = Agent(configs=[], system="x", tools=[_measure()],
                      usage_cfg={"agent": {"daily_usd_cap": 0.01}})
        m = Mock()
        with patch("agent.loop.complete_with_fallback", m):
            out = agent.run("hello")
        self.assertIn("USD cap", out)
        m.assert_not_called()


if __name__ == "__main__":
    unittest.main()
