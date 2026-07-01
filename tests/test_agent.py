"""Test suite — run with:  python -m unittest discover -s tests
Stdlib-only (unittest), no network, no API key. Covers the safety-critical logic:
provider routing, the human gates, tool dispatch, Telegram parsing, and the setup writers."""
import json
import tempfile
import unittest
from pathlib import Path

from agent.llm import config_from_dict
from agent.loop import Agent, Tool
from agent.tools import DEFAULT_TOOLS
from agent import setup as setup_mod
from agent.telegram import TelegramGateway


class TestProviderRouting(unittest.TestCase):
    def test_all_aliases_dispatch_to_a_real_provider(self):
        for alias in ["gemini", "groq", "ollama", "openrouter", "mistral", "openai", "anthropic", "claude-code"]:
            c = config_from_dict({"provider": alias, "model": "x"})
            self.assertIn(c.provider, ("openai", "anthropic", "claude-code"), f"{alias} -> {c.provider}")

    def test_gemini_uses_openai_endpoint_and_key(self):
        c = config_from_dict({"provider": "gemini", "model": "gemini-2.5-flash"})
        self.assertEqual(c.provider, "openai")
        self.assertEqual(c.api_key_env, "GEMINI_API_KEY")
        self.assertIn("generativelanguage", c.base_url)

    def test_custom_base_url_is_kept(self):
        c = config_from_dict({"provider": "openai", "base_url": "https://x/v1", "model": "m"})
        self.assertEqual(c.base_url, "https://x/v1")


class TestGates(unittest.TestCase):
    def _agent(self, approver):
        tools = [
            Tool("measure", "", {"type": "object", "properties": {}}, lambda a: "ok", "autonomous"),
            Tool("send", "", {"type": "object", "properties": {}}, lambda a: "SENT", "ask_first"),
            Tool("create_account", "", {"type": "object", "properties": {}}, lambda a: "MADE", "never"),
            Tool("boom", "", {"type": "object", "properties": {}},
                 lambda a: (_ for _ in ()).throw(ValueError("kaboom")), "autonomous"),
        ]
        return Agent(configs=[], system="x", tools=tools, approver=approver)

    def test_autonomous_runs(self):
        self.assertEqual(self._agent(lambda n, a: False)._exec("measure", {}), "ok")

    def test_ask_first_blocked_without_approval(self):
        self.assertIn("NOT DONE", self._agent(lambda n, a: False)._exec("send", {}))

    def test_ask_first_runs_with_approval(self):
        self.assertEqual(self._agent(lambda n, a: True)._exec("send", {}), "SENT")

    def test_never_is_refused(self):
        self.assertIn("REFUSED", self._agent(lambda n, a: True)._exec("create_account", {}))

    def test_unknown_tool(self):
        self.assertIn("unknown tool", self._agent(lambda n, a: True)._exec("nope", {}))

    def test_tool_crash_is_caught(self):
        self.assertIn("kaboom", self._agent(lambda n, a: True)._exec("boom", {}))


class TestTools(unittest.TestCase):
    def test_schema_shape(self):
        t = DEFAULT_TOOLS[0].schema()
        self.assertEqual(t["type"], "function")
        self.assertIn("name", t["function"])

    def test_gates_assigned(self):
        g = {t.name: t.gate for t in DEFAULT_TOOLS}
        self.assertEqual(g["read_file"], "autonomous")
        self.assertEqual(g["web_fetch"], "ask_first")   # egress channel — gated by default
        self.assertEqual(g["write_file"], "ask_first")
        self.assertNotIn("run_shell", g)          # opt-in only — not in the safe default set

    def test_web_fetch_autonomous_is_opt_in(self):
        from agent.tools import build_default_tools
        gate = lambda cfg: {t.name: t.gate for t in build_default_tools(cfg)}["web_fetch"]
        self.assertEqual(gate({}), "ask_first")                                       # safe default
        self.assertEqual(gate({"tools": {"web_fetch": {"autonomous": True}}}), "autonomous")
        self.assertEqual(gate({"tools": {"web_fetch": {"autonomous": "false"}}}), "ask_first")  # strict

    def test_run_shell_is_opt_in(self):
        from agent.tools import build_default_tools
        names = lambda cfg: {t.name for t in build_default_tools(cfg)}
        self.assertNotIn("run_shell", names({}))
        self.assertNotIn("run_shell", names({"tools": {"run_shell": {"enabled": False}}}))
        enabled = build_default_tools({"tools": {"run_shell": {"enabled": True}}})
        self.assertEqual({t.name: t.gate for t in enabled}.get("run_shell"), "ask_first")

    def test_run_shell_enable_is_strict(self):
        # a QUOTED yaml 'false'/'no' loads as a string; bool('false') is True, so it must NOT enable
        from agent.tools import build_default_tools
        has = lambda v: "run_shell" in {t.name for t in build_default_tools({"tools": {"run_shell": {"enabled": v}}})}
        for off in ("false", "no", "off", "0", "", 0, None):
            self.assertFalse(has(off), f"{off!r} must not enable run_shell")
        for on in (True, "true", "yes", "on", "1", 1):
            self.assertTrue(has(on), f"{on!r} should enable run_shell")


class TestToolHardening(unittest.TestCase):
    def test_write_file_refuses_outside_workdir(self):
        import os, tempfile
        from agent import tools as tl
        d = tempfile.mkdtemp()
        os.environ["AGENT_WORKDIR"] = d
        try:
            outside = os.path.join(os.path.dirname(d), "escape_outside.txt")
            r = tl._write_file({"path": outside, "content": "x"})
            self.assertIn("refused", r.lower())
            self.assertFalse(os.path.exists(outside))   # nothing written outside the jail
        finally:
            os.environ.pop("AGENT_WORKDIR", None)

    def test_write_file_allows_inside_workdir(self):
        import os, tempfile
        from agent import tools as tl
        d = tempfile.mkdtemp()
        os.environ["AGENT_WORKDIR"] = d
        try:
            inside = os.path.join(d, "sub", "ok.txt")
            r = tl._write_file({"path": inside, "content": "hello"})
            self.assertIn("wrote", r)
            with open(inside, encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello")
        finally:
            os.environ.pop("AGENT_WORKDIR", None)

    def test_run_shell_uses_argv_not_shell(self):
        # the injection ';' must become an inert arg, not a chained second command
        from agent import tools as tl
        captured = {}

        def fake_run(argv, **kw):
            captured["argv"], captured["kw"] = argv, kw

            class R:
                stdout, stderr, returncode = "ok", "", 0
            return R()

        orig = tl.subprocess.run
        tl.subprocess.run = fake_run
        try:
            tl._run_shell({"command": "echo hi; rm -rf /"})
        finally:
            tl.subprocess.run = orig
        self.assertEqual(captured["argv"], ["echo", "hi;", "rm", "-rf", "/"])
        self.assertNotIn("shell", captured["kw"])       # no shell=True


class TestTelegramParsing(unittest.TestCase):
    def _gw(self, scripted):
        gw = TelegramGateway.__new__(TelegramGateway)
        gw.token, gw.allowed, gw.offset, gw.logger = "x", {42}, 0, lambda m: None
        gw._scripted = list(scripted)
        gw._api = lambda method, **p: (gw._scripted.pop(0) if gw._scripted else {"ok": True, "result": []})
        return gw

    def test_pull_parses_and_advances_offset(self):
        gw = self._gw([{"ok": True, "result": [
            {"update_id": 10, "message": {"from": {"id": 42}, "chat": {"id": 7}, "text": "hi"}},
            {"update_id": 11, "message": {"from": {"id": 42}, "chat": {"id": 7}}},  # no text -> skipped
        ]}])
        msgs = gw._pull(timeout=0)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["text"], "hi")
        self.assertEqual(gw.offset, 12)  # advanced past the highest update_id

    def test_pull_surfaces_callback_query(self):
        gw = self._gw([{"ok": True, "result": [
            {"update_id": 5, "callback_query": {
                "id": "cb1", "from": {"id": 42},
                "message": {"chat": {"id": 7}}, "data": "approve"}}]}])
        msgs = gw._pull(timeout=0)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["data"], "approve")
        self.assertEqual(msgs[0]["callback_id"], "cb1")
        self.assertEqual(gw.offset, 6)

    def test_wait_approval_button_approve_returns_true(self):
        gw = self._gw([{"ok": True, "result": [
            {"update_id": 1, "callback_query": {
                "id": "cb1", "from": {"id": 42},
                "message": {"chat": {"id": 7}}, "data": "approve"}}]}])
        self.assertTrue(gw._wait_approval(7, timeout_s=20))

    def test_wait_approval_button_deny_returns_false(self):
        gw = self._gw([{"ok": True, "result": [
            {"update_id": 1, "callback_query": {
                "id": "cb2", "from": {"id": 42},
                "message": {"chat": {"id": 7}}, "data": "deny"}}]}])
        self.assertFalse(gw._wait_approval(7, timeout_s=20))

    def test_wait_approval_typed_text_fallback(self):
        gw = self._gw([{"ok": True, "result": [
            {"update_id": 1, "message": {"from": {"id": 42}, "chat": {"id": 7}, "text": "yes"}}]}])
        self.assertTrue(gw._wait_approval(7, timeout_s=20))
        gw = self._gw([{"ok": True, "result": [
            {"update_id": 1, "message": {"from": {"id": 42}, "chat": {"id": 7}, "text": "no"}}]}])
        self.assertFalse(gw._wait_approval(7, timeout_s=20))


class TestSetupWriters(unittest.TestCase):
    def test_writes_valid_config_and_user(self):
        import yaml
        d = Path(tempfile.mkdtemp())
        (d / "identity").mkdir()
        setup_mod.write_config(d, "Aria", "Jane", "gemini", "gemini-2.5-flash", False)
        setup_mod.write_user(d, "Jane", "founder", "CET")
        y = yaml.safe_load((d / "config.yaml").read_text())
        self.assertEqual(y["model"]["provider"], "gemini")
        self.assertEqual(y["gates"]["never"], ["create_account", "enter_credentials", "solve_captcha", "accept_terms"])
        self.assertIn("Jane", (d / "identity" / "USER.md").read_text())


class TestWebTool(unittest.TestCase):
    def test_candidates_drop_stopwords(self):
        from agent.tools_web import _candidates
        cands = _candidates("Bakkerij Dumalin", "Deinze")
        self.assertIn("dumalin.be", cands)            # brand token, sector word dropped

    def test_owns_rejects_parked_and_accepts_real(self):
        from agent.tools_web import _owns
        self.assertFalse(_owns("<title>Premium Domain For Sale</title>", "Dumalin", "Deinze", False))
        self.assertTrue(_owns("<title>Bakkerij Dumalin Deinze</title><body>dumalin deinze</body>",
                              "Bakkerij Dumalin", "Deinze", False))

    def test_strict_com_needs_town(self):
        from agent.tools_web import _owns
        # generic .com with the name but no town -> not owned (strict)
        self.assertFalse(_owns("<title>Steven</title><body>steven</body>", "Slagerij Steven", "Astene", True))

    def test_tool_registered(self):
        from agent.tools_web import WEB_TOOLS
        self.assertEqual(WEB_TOOLS[0].name, "verify_website")
        self.assertEqual(WEB_TOOLS[0].gate, "autonomous")


if __name__ == "__main__":
    unittest.main()
