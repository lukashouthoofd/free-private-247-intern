"""
The agent's tool-calling loop — model-agnostic (built on agent.llm).

ReAct-style: inject identity + skills as the system prompt, call the model with the tool
schemas, run whatever tools it asks for, feed the results back, repeat until it answers or
hits max_steps (the anti-runaway cap).

Human-in-the-loop gates are enforced HERE, not left to the model's goodwill:
  - autonomous : run freely (read, research, measure, draft)
  - ask_first  : require operator approval before running (send, post, pay, ...)
  - never      : always refused (create account, enter credentials, solve captcha, ...)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from .llm import LLMConfig, complete_with_fallback


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                 # JSON Schema for the args
    fn: Callable[[dict], object]     # (args) -> result (stringified for the model)
    gate: str = "autonomous"         # autonomous | ask_first | never

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class Agent:
    configs: list[LLMConfig]                       # primary + fallbacks
    system: str                                    # identity + behavior contract + skills
    tools: list[Tool] = field(default_factory=list)
    max_steps: int = 20
    approver: Callable[[str, dict], bool] = lambda name, args: False   # default: deny ask_first
    logger: Callable[[str], None] = print
    usage_cfg: dict = field(default_factory=dict)   # full config dict — for the daily spend cap

    def __post_init__(self):
        self._tools = {t.name: t for t in self.tools}

    def run(self, user_msg: str, history: list[dict] | None = None) -> str:
        messages = [{"role": "system", "content": self.system}]
        messages += history or []
        messages.append({"role": "user", "content": user_msg})
        schemas = [t.schema() for t in self.tools] or None

        for step in range(self.max_steps):
            from .usage import over_cap
            blocked, reason = over_cap(self.usage_cfg)
            if blocked:
                return f"(stopped: {reason} — daily spend cap hit, refusing further API calls)"
            out = complete_with_fallback(self.configs, messages, schemas)
            calls = out.get("tool_calls") or []
            if not calls:
                return out.get("content", "")
            self.logger(f"  step {step + 1}: {len(calls)} tool call(s)")
            messages.append({"role": "assistant", "content": out.get("content") or "", "tool_calls": calls})
            for c in calls:
                name = (c.get("function") or {}).get("name", "")
                try:
                    args = json.loads((c.get("function") or {}).get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = str(self._exec(name, args))
                messages.append({"role": "tool", "tool_call_id": c.get("id"), "name": name,
                                 "content": result[:8000] + ("\n...[truncated]" if len(result) > 8000 else "")})
        return "(stopped: reached max_steps — the loop was capped to prevent runaway cost)"

    def _exec(self, name: str, args: dict) -> str:
        t = self._tools.get(name)
        if not t:
            return f"ERROR: unknown tool '{name}'"
        if t.gate == "never":
            return f"REFUSED: '{name}' is a red-line action this agent never performs."
        if t.gate == "ask_first" and not self.approver(name, args):
            return f"NOT DONE: '{name}' needs operator approval and it was not granted. Prepare it and ask."
        self.logger(f"    -> {name}({json.dumps(args)[:120]})")
        try:
            return str(t.fn(args))
        except Exception as e:  # tools must never crash the loop
            return f"ERROR running '{name}': {e}"
