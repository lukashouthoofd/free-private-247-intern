"""Hardening tests for agent/llm.py — provider robustness (issue #1).
Stdlib-only (unittest + unittest.mock), no network, no API key. Covers:
alias validation, OSError/429 handling in _http_json, empty/error response bodies,
the claude-code empty-stdout case, the alias-in-diagnostics, and the fallback chain."""
import io
import unittest
from unittest import mock

from agent import llm
from agent.llm import (
    LLMConfig,
    LLMError,
    _CANONICAL_PROVIDERS,
    complete_with_fallback,
    config_from_dict,
)


# --- llm-1: unknown alias is rejected at construction -----------------------

class TestAliasValidation(unittest.TestCase):
    def test_known_alias_builds(self):
        c = config_from_dict({"provider": "gemini", "model": "x"})
        self.assertEqual(c.provider, "openai")
        self.assertEqual(c.alias, "gemini")

    def test_canonical_provider_builds(self):
        for p in _CANONICAL_PROVIDERS:
            c = config_from_dict({"provider": p, "model": "x"})
            self.assertEqual(c.alias, p)

    def test_unknown_alias_raises_early(self):
        with self.assertRaises(LLMError) as ctx:
            config_from_dict({"provider": "gemnini", "model": "x"})  # typo
        self.assertIn("unknown provider alias", str(ctx.exception))
        self.assertIn("gemnini", str(ctx.exception))

    def test_default_provider_is_openai(self):
        c = config_from_dict({"model": "x"})  # no provider -> openai
        self.assertEqual(c.provider, "openai")
        self.assertEqual(c.alias, "openai")


# --- llm-7: original alias carried for diagnostics --------------------------

class TestAliasDiagnostics(unittest.TestCase):
    def test_missing_key_reports_alias_not_dispatch_provider(self):
        c = config_from_dict({"provider": "gemini", "model": "x"})  # -> provider openai
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=False):
            with self.assertRaises(LLMError) as ctx:
                llm._complete_openai(c, [{"role": "user", "content": "hi"}], None)
        msg = str(ctx.exception)
        self.assertIn("gemini", msg)          # operator-facing alias
        self.assertIn("GEMINI_API_KEY", msg)

    def test_alias_field_default_empty(self):
        # direct construction (not via config_from_dict) still works, alias defaults to ""
        self.assertEqual(LLMConfig().alias, "")


# --- llm-2 / llm-3: _http_json error handling -------------------------------

def _http_error(code, headers=None):
    import urllib.error
    return urllib.error.HTTPError(
        url="https://x/v1/chat/completions", code=code,
        msg="err", hdrs=headers or {}, fp=io.BytesIO(b'{"error":"x"}'))


class TestHttpJson(unittest.TestCase):
    def test_oserror_is_caught_as_llmerror(self):
        # ConnectionRefusedError is OSError but NOT URLError (local Ollama down).
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
            with self.assertRaises(LLMError) as ctx:
                llm._http_json("http://localhost:11434/v1/x", {}, {}, 1)
        self.assertIn("connection error", str(ctx.exception))

    def test_timeout_is_caught_as_llmerror(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaises(LLMError):
                llm._http_json("https://x/v1/x", {}, {}, 1)

    def test_429_sleeps_with_retry_after_then_raises(self):
        err = _http_error(429, {"Retry-After": "0.01"})
        with mock.patch("urllib.request.urlopen", side_effect=err), \
             mock.patch("agent.llm.time.sleep") as slept:
            with self.assertRaises(LLMError) as ctx:
                llm._http_json("https://x/v1/x", {}, {}, 1)
        slept.assert_called_once()
        self.assertAlmostEqual(slept.call_args[0][0], 0.01, places=3)
        self.assertIn("HTTP 429", str(ctx.exception))

    def test_503_sleeps_capped_at_30(self):
        err = _http_error(503, {"Retry-After": "999"})
        with mock.patch("urllib.request.urlopen", side_effect=err), \
             mock.patch("agent.llm.time.sleep") as slept:
            with self.assertRaises(LLMError):
                llm._http_json("https://x/v1/x", {}, {}, 1)
        self.assertEqual(slept.call_args[0][0], 30.0)

    def test_429_bad_retry_after_defaults_to_2(self):
        err = _http_error(429, {"Retry-After": "soon"})  # non-numeric
        with mock.patch("urllib.request.urlopen", side_effect=err), \
             mock.patch("agent.llm.time.sleep") as slept:
            with self.assertRaises(LLMError):
                llm._http_json("https://x/v1/x", {}, {}, 1)
        self.assertEqual(slept.call_args[0][0], 2.0)

    def test_other_http_error_does_not_sleep(self):
        err = _http_error(400)
        with mock.patch("urllib.request.urlopen", side_effect=err), \
             mock.patch("agent.llm.time.sleep") as slept:
            with self.assertRaises(LLMError) as ctx:
                llm._http_json("https://x/v1/x", {}, {}, 1)
        slept.assert_not_called()
        self.assertIn("HTTP 400", str(ctx.exception))


# --- llm-6: HTTP-200 error / empty bodies are surfaced ----------------------

class TestEmptyAndErrorBodies(unittest.TestCase):
    def _cfg(self):
        return config_from_dict({"provider": "openai", "model": "m", "base_url": "https://x/v1"})

    def test_openai_no_choices_raises(self):
        c = self._cfg()
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "k"}, clear=False), \
             mock.patch("agent.llm._http_json", return_value={"choices": []}):
            with self.assertRaises(LLMError) as ctx:
                llm._complete_openai(c, [{"role": "user", "content": "hi"}], None)
        self.assertIn("no choices", str(ctx.exception))

    def test_openai_valid_choice_does_not_crash(self):
        c = self._cfg()
        good = {"choices": [{"message": {"content": "hello"}}], "usage": {}}
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "k"}, clear=False), \
             mock.patch("agent.llm._http_json", return_value=good):
            out = llm._complete_openai(c, [{"role": "user", "content": "hi"}], None)
        self.assertEqual(out["content"], "hello")

    def test_anthropic_error_body_raises(self):
        c = config_from_dict({"provider": "anthropic", "model": "m"})
        err_body = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             mock.patch("agent.llm._http_json", return_value=err_body):
            with self.assertRaises(LLMError) as ctx:
                llm._complete_anthropic(c, [{"role": "user", "content": "hi"}], None)
        self.assertIn("Anthropic error", str(ctx.exception))

    def test_anthropic_valid_body_does_not_crash(self):
        c = config_from_dict({"provider": "anthropic", "model": "m"})
        body = {"content": [{"type": "text", "text": "hi there"}], "usage": {}}
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             mock.patch("agent.llm._http_json", return_value=body):
            out = llm._complete_anthropic(c, [{"role": "user", "content": "hi"}], None)
        self.assertEqual(out["content"], "hi there")


# --- llm-5: claude-code exit-0 + empty stdout is surfaced -------------------

class _Proc:
    def __init__(self, rc, stdout, stderr=""):
        self.returncode, self.stdout, self.stderr = rc, stdout, stderr


class TestClaudeCodeEmptyOutput(unittest.TestCase):
    def _cfg(self):
        return config_from_dict({"provider": "claude-code", "model": ""})

    def test_empty_stdout_raises(self):
        with mock.patch("subprocess.run", return_value=_Proc(0, "   \n")):
            with self.assertRaises(LLMError) as ctx:
                llm._complete_claude_code(self._cfg(), [{"role": "user", "content": "hi"}], None)
        self.assertIn("no output", str(ctx.exception))

    def test_plain_text_stdout_still_works(self):
        with mock.patch("subprocess.run", return_value=_Proc(0, "hello world")):
            out = llm._complete_claude_code(self._cfg(), [{"role": "user", "content": "hi"}], None)
        self.assertEqual(out["content"], "hello world")

    def test_json_stdout_parsed(self):
        with mock.patch("subprocess.run", return_value=_Proc(0, '{"result": "ok"}')):
            out = llm._complete_claude_code(self._cfg(), [{"role": "user", "content": "hi"}], None)
        self.assertEqual(out["content"], "ok")


# --- testgap-13 / testgap-14: fallback chain --------------------------------

class TestFallbackChain(unittest.TestCase):
    def test_all_providers_failed(self):
        cfg = config_from_dict({"provider": "gemini", "model": "x"})
        with mock.patch("agent.llm.complete", side_effect=LLMError("boom")):
            with self.assertRaises(LLMError) as ctx:
                complete_with_fallback([cfg, cfg], [])
        self.assertIn("all providers failed", str(ctx.exception))

    def test_recovers_on_second_provider(self):
        cfg_a = config_from_dict({"provider": "gemini", "model": "a"})
        cfg_b = config_from_dict({"provider": "groq", "model": "b"})
        attempted = []

        def side(cfg, messages, tools=None):
            attempted.append(cfg.model)
            if cfg.model == "a":
                raise LLMError("quota")
            return {"content": "ok", "tool_calls": [], "usage": {}, "raw": None}

        with mock.patch("agent.llm.complete", side_effect=side):
            out = complete_with_fallback([cfg_a, cfg_b], [])
        self.assertEqual(out["content"], "ok")
        self.assertEqual(attempted, ["a", "b"])  # both tried, in order


if __name__ == "__main__":
    unittest.main()
