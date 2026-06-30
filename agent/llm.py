"""
Model-agnostic LLM client — pick your brain via config + .env, no code change.

Providers (set `model.provider` in config.yaml):
  - openai      : ANY OpenAI-compatible /chat/completions endpoint. Covers OpenAI, Groq,
                  Together, OpenRouter, Mistral, DeepSeek, a LOCAL Ollama server (/v1), and
                  Google Gemini (its OpenAI-compatible endpoint). Just set base_url + model
                  + the env var that holds the key.
  - anthropic   : native Anthropic Messages API (set ANTHROPIC_API_KEY).
  - claude-code : shell out to the `claude -p` CLI. Uses a Claude Code / Max *subscription*
                  (no API key, not metered). Best if you already pay for Claude.

Design goals: zero third-party dependencies (stdlib urllib + json + subprocess) so it runs
on any old Debian box with just Python 3, and a single normalized return shape so the agent
loop never has to care which provider is behind it.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    provider: str = "openai"          # openai | anthropic | claude-code
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    max_tokens: int = 2048
    temperature: float = 0.3
    timeout: int = 120
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


# Convenience presets so config can say e.g. provider: gemini and we fill the rest.
PRESETS: dict[str, dict[str, Any]] = {
    "openai":     {"provider": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "gemini":     {"provider": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "api_key_env": "GEMINI_API_KEY"},
    "groq":       {"provider": "openai", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    "openrouter": {"provider": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "mistral":    {"provider": "openai", "base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"},
    "ollama":     {"provider": "openai", "base_url": "http://localhost:11434/v1", "api_key_env": "OLLAMA_API_KEY"},  # key unused/optional
    "anthropic":  {"provider": "anthropic", "base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY"},
    "claude-code": {"provider": "claude-code", "base_url": "", "api_key_env": ""},
}


def config_from_dict(d: dict[str, Any]) -> LLMConfig:
    """Build an LLMConfig from a config.yaml `model:` block.

    Accepts either an explicit provider (openai/anthropic/claude-code) or a friendly
    alias (gemini/groq/openrouter/mistral/ollama) that expands via PRESETS. Any field
    in the dict overrides the preset, so you can point `openai` at any base_url.
    """
    d = dict(d or {})
    # `provider` in the config is an ALIAS used to pick the preset (gemini/groq/ollama/...).
    # The preset supplies the REAL dispatch provider (openai/anthropic/claude-code) + base_url +
    # key env. Pop the alias first so it can't clobber the preset's real provider on update().
    alias = d.pop("provider", "openai")
    merged = dict(PRESETS.get(alias) or {"provider": alias})
    merged.update({k: v for k, v in d.items() if v is not None})
    return LLMConfig(
        provider=merged.get("provider", "openai"),
        model=merged.get("model") or merged.get("default") or "gpt-4o-mini",
        base_url=merged.get("base_url", "https://api.openai.com/v1"),
        api_key_env=merged.get("api_key_env", "OPENAI_API_KEY"),
        max_tokens=int(merged.get("max_tokens", 2048)),
        temperature=float(merged.get("temperature", 0.3)),
        timeout=int(merged.get("timeout", 120)),
        extra_headers=merged.get("extra_headers", {}) or {},
    )


def _http_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        raise LLMError(f"HTTP {e.code} from {url}: {body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"connection error to {url}: {e}") from e


def _norm(content: str = "", tool_calls: list | None = None, usage: dict | None = None, raw: Any = None) -> dict:
    return {"content": content or "", "tool_calls": tool_calls or [], "usage": usage or {}, "raw": raw}


# --- providers -------------------------------------------------------------

def _complete_openai(cfg: LLMConfig, messages: list[dict], tools: list | None) -> dict:
    if not cfg.api_key and "localhost" not in cfg.base_url:
        raise LLMError(f"no API key in ${cfg.api_key_env} for provider {cfg.provider}/{cfg.model}")
    payload: dict[str, Any] = {"model": cfg.model, "messages": messages,
                               "max_tokens": cfg.max_tokens, "temperature": cfg.temperature}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {cfg.api_key}", **cfg.extra_headers}
    data = _http_json(cfg.base_url.rstrip("/") + "/chat/completions", payload, headers, cfg.timeout)
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    return _norm(msg.get("content") or "", msg.get("tool_calls") or [], data.get("usage"), data)


def _complete_anthropic(cfg: LLMConfig, messages: list[dict], tools: list | None) -> dict:
    if not cfg.api_key:
        raise LLMError(f"no API key in ${cfg.api_key_env} for anthropic/{cfg.model}")
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    conv = [{"role": ("assistant" if m["role"] == "assistant" else "user"),
             "content": m.get("content", "")}
            for m in messages if m.get("role") in ("user", "assistant")]
    payload: dict[str, Any] = {"model": cfg.model, "max_tokens": cfg.max_tokens,
                               "temperature": cfg.temperature, "messages": conv}
    if system:
        payload["system"] = system
    if tools:  # convert OpenAI tool schema -> Anthropic
        payload["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                             "input_schema": t["function"].get("parameters", {})} for t in tools]
    headers = {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01", **cfg.extra_headers}
    data = _http_json(cfg.base_url.rstrip("/") + "/v1/messages", payload, headers, cfg.timeout)
    text, calls = "", []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
        elif block.get("type") == "tool_use":
            calls.append({"id": block.get("id"), "type": "function",
                          "function": {"name": block.get("name"), "arguments": json.dumps(block.get("input", {}))}})
    return _norm(text, calls, data.get("usage"), data)


def _complete_claude_code(cfg: LLMConfig, messages: list[dict], tools: list | None) -> dict:
    """Shell out to `claude -p`. Tool-calling is handled by Claude Code itself (it has its
    own tools); here we hand it the conversation as a single prompt and take its final text.
    Uses your Claude subscription via the logged-in CLI / CLAUDE_CODE_OAUTH_TOKEN."""
    prompt = "\n\n".join(f"[{m['role']}] {m.get('content','')}" for m in messages if m.get("content"))
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if cfg.model:
        cmd += ["--model", cfg.model]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.timeout)
    except FileNotFoundError as e:
        raise LLMError("`claude` CLI not found on PATH (install Claude Code or pick another provider)") from e
    except subprocess.TimeoutExpired as e:
        raise LLMError("claude -p timed out") from e
    if out.returncode != 0:
        raise LLMError(f"claude -p exit {out.returncode}: {out.stderr[:400]}")
    try:
        j = json.loads(out.stdout)
        return _norm(j.get("result", out.stdout), [], {"total_cost_usd": j.get("total_cost_usd")}, j)
    except json.JSONDecodeError:
        return _norm(out.stdout.strip(), [], {}, out.stdout)


_DISPATCH = {"openai": _complete_openai, "anthropic": _complete_anthropic, "claude-code": _complete_claude_code}


def complete(cfg: LLMConfig, messages: list[dict], tools: list | None = None) -> dict:
    """Run one completion. Returns {content, tool_calls, usage, raw}. Raises LLMError."""
    fn = _DISPATCH.get(cfg.provider)
    if not fn:
        raise LLMError(f"unknown provider '{cfg.provider}' (use: openai/anthropic/claude-code, or an alias)")
    return fn(cfg, messages, tools)


def complete_with_fallback(cfgs: list[LLMConfig], messages: list[dict], tools: list | None = None) -> dict:
    """Try each config in order; on LLMError fall through to the next. Keeps the agent
    alive when the primary's quota is gone (it just gets slower, not dead)."""
    last: Exception | None = None
    for cfg in cfgs:
        try:
            return complete(cfg, messages, tools)
        except LLMError as e:
            last = e
    raise LLMError(f"all providers failed; last error: {last}")


if __name__ == "__main__":  # tiny smoke test: `python -m agent.llm "hello"`
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Say hi in 5 words."
    prov = os.environ.get("AGENT_PROVIDER", "gemini")
    cfg = config_from_dict({"provider": prov, "model": os.environ.get("AGENT_MODEL", "gemini-2.5-flash")})
    print(f"[provider={cfg.provider} model={cfg.model} key_env={cfg.api_key_env} set={'yes' if cfg.api_key else 'NO'}]")
    print(complete(cfg, [{"role": "user", "content": prompt}])["content"])
