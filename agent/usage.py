"""
Usage / cost log + spend cap — the financial dead-man's-switch.

A self-hosted agent on metered APIs can quietly burn money in a runaway loop. This module
records every successful provider call to an append-only JSON-Lines log (one line per call)
and lets the caller refuse to make another call once a daily call-count or USD cap is hit.

Storage is data/usage.jsonl: append-only, so a crash mid-write loses at worst the last line.
The data dir is created lazily on first write; every read tolerates a missing/corrupt file
(returns 0) so the agent never crashes on a fresh install or a half-written log.

The token/cost fields come from whatever agent.llm.complete() puts in result['usage'] — which
differs per provider (OpenAI: prompt_tokens/completion_tokens; Anthropic: input_tokens/
output_tokens; claude-code: total_cost_usd; ollama: often empty). We parse DEFENSIVELY:
any missing field is 0/null, never an exception.

USAGE_TOOLS exports a single 'usage_summary' tool (gate autonomous — reading your own meter
on your own box is not an outward action).
"""
from __future__ import annotations

import json
import os
import time

from .loop import Tool

# Resolve the usage dir from USAGE_DIR (set by the caller/config) or fall back to ./data.
# Kept as a function so tests can monkeypatch the env var per-tempdir; real data/ stays untouched.
_DEFAULT_DIR = "data"


def _dir() -> str:
    return os.environ.get("USAGE_DIR", _DEFAULT_DIR)


def _path() -> str:
    return os.path.join(_dir(), "usage.jsonl")


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _num(v) -> float:
    """Coerce anything to a float; None/garbage -> 0.0. Never raises."""
    try:
        if v is None:
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _extract(usage: dict) -> tuple[int, int, float | None]:
    """Pull (input_tokens, output_tokens, cost_usd) out of a provider 'usage' dict.

    Defensive: accepts OpenAI (prompt_tokens/completion_tokens), Anthropic (input_tokens/
    output_tokens) and claude-code (total_cost_usd) shapes, or an empty/None dict. Any
    missing field becomes 0 (tokens) or None (cost)."""
    u = usage if isinstance(usage, dict) else {}
    inp = _num(u.get("input_tokens", u.get("prompt_tokens", 0)))
    out = _num(u.get("output_tokens", u.get("completion_tokens", 0)))
    cost_raw = u.get("cost_usd", u.get("total_cost_usd"))
    cost = None if cost_raw is None else _num(cost_raw)
    return int(inp), int(out), cost


def record(provider: str, model: str, usage_dict: dict | None) -> dict:
    """Append one usage line for a successful provider call. Returns the stored record.
    Creates data/ lazily; never raises (a logging failure must not kill a real call)."""
    inp, out, cost = _extract(usage_dict or {})
    rec = {
        "date": _today(),
        "provider": (provider or "").strip() or "unknown",
        "model": (model or "").strip() or "unknown",
        "input_tokens": inp,
        "output_tokens": out,
        "cost_usd": cost,
    }
    try:
        os.makedirs(_dir(), exist_ok=True)
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging is best-effort; never crash the agent on a write failure
    return rec


def _today_lines() -> list[dict]:
    """Every recorded line for today. Missing file -> []. Bad lines are skipped, not fatal."""
    path = _path()
    if not os.path.exists(path):
        return []
    today = _today()
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and rec.get("date") == today:
                    out.append(rec)
    except OSError:
        return []
    return out


def today_calls() -> int:
    """Number of provider calls logged today. Crash-safe -> 0 on any error."""
    return len(_today_lines())


def today_spend_usd() -> float:
    """Total cost_usd logged today (rows with null cost count as 0). Crash-safe -> 0.0."""
    return round(sum(_num(r.get("cost_usd")) for r in _today_lines()), 6)


def over_cap(cfg: dict) -> tuple[bool, str]:
    """True if today's usage has hit a configured cap. Reads agent.daily_call_cap and
    agent.daily_usd_cap; 0 or absent = unlimited. Returns (over, human-readable reason)."""
    agent = (cfg or {}).get("agent") or {}
    call_cap = _num(agent.get("daily_call_cap", 0))
    usd_cap = _num(agent.get("daily_usd_cap", 0))
    if call_cap > 0:
        calls = today_calls()
        if calls >= call_cap:
            return True, f"daily call cap reached: {calls}/{int(call_cap)} calls today"
    if usd_cap > 0:
        spend = today_spend_usd()
        if spend >= usd_cap:
            return True, f"daily USD cap reached: ${spend:.4f}/${usd_cap:.2f} spent today"
    return False, ""


def _usage_summary(args: dict) -> str:
    spend = today_spend_usd()
    return f"today: {today_calls()} call(s), ${spend:.4f} spent ({_today()})"


USAGE_TOOLS = [
    Tool("usage_summary",
         "Report today's API usage so far: number of model calls and total USD spent. "
         "Read-only meter on your own box.",
         {"type": "object", "properties": {}},
         _usage_summary, "autonomous"),
]
