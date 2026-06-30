"""Command-line entry: `python -m agent [chat|selftest]`."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .llm import complete, config_from_dict, LLMError
from .loop import Agent
from .tools import DEFAULT_TOOLS
from .tools_web import WEB_TOOLS
from .memory import MEMORY_TOOLS
from .tools_email import EMAIL_TOOLS

TOOLS = DEFAULT_TOOLS + WEB_TOOLS + MEMORY_TOOLS + EMAIL_TOOLS


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines from .env into the environment (does not override existing vars).
    Tiny stdlib parser — so `python -m agent ...` just works after `agent setup`, no exporting."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        p = Path("config.example.yaml")          # so selftest works before you copy the file
    try:
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except ImportError:
        print("note: PyYAML not installed (`pip install pyyaml`) — using built-in defaults.")
        return {"model": {"provider": "gemini", "model": "gemini-2.5-flash"}, "agent": {}}
    except FileNotFoundError:
        return {"model": {"provider": "gemini", "model": "gemini-2.5-flash"}, "agent": {}}


def build_configs(cfg: dict):
    primary = config_from_dict(cfg.get("model", {}))
    fallbacks = [config_from_dict(f) for f in (cfg.get("fallback") or [])]
    return [primary] + fallbacks


def system_prompt(cfg: dict) -> str:
    name = (cfg.get("agent") or {}).get("name", "Assistant")
    ident = ""
    for f in ("identity/SOUL.md", "identity/USER.md"):
        if Path(f).exists():
            ident += "\n\n" + Path(f).read_text(encoding="utf-8")
    return (f"You are {name}, a careful self-hosted assistant on the operator's own machine. "
            f"Use tools to do real work; never invent results. Prepare outward actions but let a "
            f"human approve them (the harness enforces this).{ident}")


def _approver(name: str, args: dict) -> bool:
    try:
        return input(f"  [approve '{name}'? y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def cmd_chat(cfg: dict) -> None:
    agent = Agent(build_configs(cfg), system_prompt(cfg), TOOLS,
                  max_steps=int((cfg.get("agent") or {}).get("max_steps", 20)), approver=_approver)
    print("agent ready — type a message, Ctrl-C to quit.")
    while True:
        try:
            msg = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if msg:
            print("\n" + agent.run(msg))


def cmd_selftest(cfg: dict) -> None:
    cfgs = build_configs(cfg)
    print("providers (in order):")
    for c in cfgs:
        keyed = "claude-code (subscription)" if c.provider == "claude-code" else ("key set" if c.api_key else "KEY MISSING")
        print(f"  - {c.provider:11} {c.model:28} [{keyed}]")
    print(f"tools: {', '.join(t.name + ('' if t.gate == 'autonomous' else f'({t.gate})') for t in TOOLS)}")
    primary = cfgs[0]
    if primary.api_key or primary.provider == "claude-code":
        try:
            r = complete(primary, [{"role": "user", "content": "Reply with exactly: ready"}])
            print("live model call ->", (r.get("content") or "").strip()[:80])
        except LLMError as e:
            print("live model call FAILED ->", e)
    else:
        print(f"no key in ${primary.api_key_env} -> set one in .env for a live call (or use provider: ollama / claude-code).")


def cmd_telegram(cfg: dict) -> None:
    from .telegram import TelegramGateway
    tg = (cfg.get("channels") or {}).get("telegram") or {}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("set TELEGRAM_BOT_TOKEN in .env, and channels.telegram.allowed_users in config.yaml")
        return
    configs, system = build_configs(cfg), system_prompt(cfg)
    max_steps = int((cfg.get("agent") or {}).get("max_steps", 20))

    def factory(approver):
        return Agent(configs, system, TOOLS, max_steps=max_steps, approver=approver)

    TelegramGateway(token, tg.get("allowed_users", []), factory).run()


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):   # never crash on a non-UTF-8 console (Windows cp1252)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = argv if argv is not None else sys.argv[1:]
    load_dotenv()
    cfg = load_config()
    os.environ.setdefault("MEMORY_DIR", str((cfg.get("memory") or {}).get("dir", "./data/memory")))
    cmd = argv[0] if argv else "selftest"
    if cmd == "chat":
        cmd_chat(cfg)
    elif cmd == "selftest":
        cmd_selftest(cfg)
    elif cmd == "telegram":
        cmd_telegram(cfg)
    elif cmd == "digest":
        from .digest import deliver
        deliver(cfg)
    elif cmd == "setup":
        from .setup import run as setup_run
        setup_run()
    else:
        print("usage: python -m agent [setup|selftest|chat|telegram|digest]")
