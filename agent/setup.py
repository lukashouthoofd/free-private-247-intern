"""
`python -m agent setup` — interactive first-run wizard.

Asks who the operator is and which model/key to use, then writes:
  - config.yaml         (your brain + agent name)
  - .env                (API keys, chmod 600 — never committed)
  - identity/USER.md    (who the agent serves)
Re-runnable; it warns before overwriting an existing file. Keys are read with getpass
(no echo) and only ever land in .env.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path

from .llm import PRESETS

DEFAULT_MODEL = {
    "gemini": "gemini-2.5-flash", "claude-code": "claude-opus-4-8", "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile", "openrouter": "openai/gpt-4o-mini",
    "mistral": "mistral-large-latest", "ollama": "qwen2.5:3b", "anthropic": "claude-sonnet-4-6",
}


def _ask(prompt: str, default: str = "") -> str:
    try:
        v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return v or default


def _choose(prompt: str, options: list[str], default: str) -> str:
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}) {o}")
    try:
        raw = input(f"choose 1-{len(options)} [{options.index(default) + 1}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    try:
        return options[int(raw) - 1]
    except (ValueError, IndexError):
        return default


def _confirm_overwrite(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        return input(f"  {path} exists — overwrite? (y/N) ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _secret(prompt: str) -> str:
    """getpass that returns '' on EOF/Ctrl-C (piped/CI stdin) instead of raising — so a
    non-interactive `python -m agent setup` writes an empty key rather than crashing."""
    try:
        return getpass.getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _yaml_dq(s: str) -> str:
    """Escape a string for safe use inside a YAML double-quoted scalar (backslash, quote, and
    strip newlines so free-text operator input can never break config.yaml's syntax)."""
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return s.replace("\r", " ").replace("\n", " ")


def write_config(root: Path, agent_name: str, operator: str, provider: str, model: str, telegram: bool) -> None:
    p = root / "config.yaml"
    if not _confirm_overwrite(p):
        print("  kept existing config.yaml")
        return
    agent_name, operator = _yaml_dq(agent_name), _yaml_dq(operator)
    p.write_text(f"""model:
  provider: {provider}
  model: {model}
  max_tokens: 2048
  temperature: 0.3

fallback:
  - {{ provider: ollama, model: qwen2.5:3b }}   # local fallback; remove if no Ollama

agent:
  name: "{agent_name}"
  operator: "{operator}"
  max_steps: 20
  reasoning_effort: medium

channels:
  cli: true
  telegram:
    enabled: {str(telegram).lower()}
    allowed_users: []          # numeric chat IDs allowed to talk to it (empty = nobody — fail closed)

tools:
  run_shell:
    enabled: false             # arbitrary command execution (ask_first). OFF by default — opt in knowingly.

gates:
  autonomous: [read, research, measure, draft]
  ask_first:  [send, submit, post, publish, signup, pay]
  never:      [create_account, enter_credentials, solve_captcha, accept_terms]

memory:
  dir: ./data/memory
  enabled: true

schedule:
  digest_hour: 6
  reflection_weekday: sun
""", encoding="utf-8")
    print("  wrote config.yaml")


def write_env(root: Path, key_env: str, key: str, telegram_token: str) -> None:
    p = root / ".env"
    lines = []
    if p.exists():
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines()
                 if not (key_env and ln.startswith(key_env + "=")) and not ln.startswith("TELEGRAM_BOT_TOKEN=")]
    if key_env and key:
        lines.append(f"{key_env}={key}")
    if telegram_token:
        lines.append(f"TELEGRAM_BOT_TOKEN={telegram_token}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass  # Windows / non-POSIX
    print("  wrote .env (chmod 600)")


def write_user(root: Path, name: str, role: str, region: str) -> None:
    p = root / "identity" / "USER.md"
    if not _confirm_overwrite(p):
        print("  kept existing identity/USER.md")
        return
    p.parent.mkdir(exist_ok=True)
    p.write_text(f"""# About the operator

> Injected into every prompt. Keep it short and factual. Keep secrets out of a public repo.

## Person & context
- Name: **{name or '<your name>'}**
- Role / business: **{role or '<your role>'}**
- Region / timezone: **{region or '<your region>'}**

## Preferences
- Short, direct, no flattery, no fabrication, production code over toy code.
""", encoding="utf-8")
    print("  wrote identity/USER.md")


def run() -> None:
    print("=== self-hosted AI employee — setup ===\n")
    agent_name = _ask("Agent name", "Intern")
    op_name = _ask("Your name (the operator)")
    op_role = _ask("Your role / business")
    op_region = _ask("Region / timezone")

    providers = ["gemini", "claude-code", "openai", "groq", "openrouter", "mistral", "ollama", "anthropic"]
    provider = _choose("\nPick your model provider (the 'brain'):", providers, "gemini")
    model = _ask("Model id", DEFAULT_MODEL.get(provider, ""))

    key_env = PRESETS.get(provider, {}).get("api_key_env", "")
    key = ""
    if provider not in ("claude-code", "ollama") and key_env:
        key = _secret(f"{key_env} (hidden — enter to skip and fill .env later): ")

    telegram = _ask("\nEnable Telegram channel? (y/N)", "N").lower() in ("y", "yes")
    tg_token = _secret("TELEGRAM_BOT_TOKEN (hidden): ") if telegram else ""

    root = Path(".")
    print()
    write_config(root, agent_name, op_name, provider, model, telegram)
    write_env(root, key_env, key, tg_token)
    write_user(root, op_name, op_role, op_region)

    print("\nsetup done.")
    if provider == "claude-code":
        print("  provider=claude-code -> run `claude setup-token` once so the box can use your subscription.")
    elif provider == "ollama":
        print("  provider=ollama -> make sure Ollama is running and the model is pulled (`ollama pull " + (model or "qwen2.5:3b") + "`).")
    elif key_env and not key:
        print(f"  ! put your key in .env as {key_env}=...")
    print("  then: python -m agent selftest   (and)   python -m agent chat")
