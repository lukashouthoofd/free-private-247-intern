"""
Proactive morning brief — what turns this from a chatbot into an employee.

build_digest(cfg) composes a short, dated brief out of recent persistent memory (agent.memory).
It is intentionally structured as a list of sections so read-only tool calls (e.g. "today's
calendar", "open tasks") can be appended later without reshaping the output.

deliver(cfg) prints the brief and, IF a Telegram token AND a chat id are configured, also pushes
it to your phone — reusing agent.telegram's send pattern. Delivery is optional and safe: no token
or no chat id => it just prints and returns. No secrets live in code; the token is read from env.

Run on a schedule via systemd/ai-employee-digest.timer (`python -m agent digest`, ~06:00 daily).
"""
from __future__ import annotations

import os
import time

from . import memory


def _chat_ids(cfg: dict) -> list[int]:
    """Where to send the brief: explicit schedule.digest_chat_id, else telegram allowed_users."""
    sched = (cfg.get("schedule") or {})
    explicit = sched.get("digest_chat_id")
    if explicit is not None:
        try:
            return [int(explicit)]
        except (TypeError, ValueError):
            return []
    tg = (cfg.get("channels") or {}).get("telegram") or {}
    out = []
    for u in (tg.get("allowed_users") or []):
        try:
            out.append(int(u))
        except (TypeError, ValueError):
            continue
    return out


def build_digest(cfg: dict, now: float | None = None) -> str:
    """Compose the morning brief from recent memory. Always returns a non-empty string."""
    cfg = cfg or {}
    name = (cfg.get("agent") or {}).get("name", "Assistant")
    operator = (cfg.get("agent") or {}).get("operator", "")
    now = time.time() if now is None else now
    today = time.strftime("%A %d %B %Y", time.localtime(now))

    sections: list[str] = []
    header = f"Daily brief — {today}"
    sections.append(header)
    sections.append(f"From {name}" + (f" for {operator}" if operator and operator != "set-me" else "") + ".")

    notes = memory.recent(10)
    if notes:
        lines = []
        for r in notes:
            when = time.strftime("%a %H:%M", time.localtime(r.get("ts", 0)))
            lines.append(f"  • [{when}] ({r.get('kind', 'note')}) {r.get('text', '')}")
        sections.append("Recent memory (latest first is at the bottom):\n" + "\n".join(lines))
    else:
        sections.append("Recent memory: (empty — nothing noted yet. Tell me things to remember.)")

    tasks = [r for r in memory.search("task") if r.get("kind") == "task"][-5:]
    if tasks:
        sections.append("Open items tagged 'task':\n"
                        + "\n".join(f"  • {r.get('text', '')}" for r in tasks))

    # Placeholder anchor: read-only tools (calendar, inbox count, weather) get appended here later.
    sections.append("(Read-only tool results — calendar, inbox — can be wired in here later.)")

    return "\n\n".join(sections)


def deliver(cfg: dict, logger=print) -> str:
    """Build the brief, print it, and push to Telegram if a token + chat id are configured.
    Returns the brief text. Never raises on missing token/config — delivery is best-effort."""
    cfg = cfg or {}
    brief = build_digest(cfg)
    logger(brief)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_ids = _chat_ids(cfg)
    if not token or not chat_ids:
        logger("(digest: not sent — no TELEGRAM_BOT_TOKEN and/or no chat id configured; printed only)")
        return brief

    try:
        from .telegram import TelegramGateway
        gw = TelegramGateway(token, [], lambda *a, **k: None, logger=logger)
        for cid in chat_ids:
            gw.send(cid, brief)
        logger(f"(digest: sent to {len(chat_ids)} chat(s))")
    except Exception as e:  # delivery is optional — never let it crash the timer
        logger(f"(digest: send failed, printed only: {e})")
    return brief
