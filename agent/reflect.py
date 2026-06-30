"""
Weekly fail-closed reflection — the agent distils durable lessons from its own memory.

This is the slow half of "learning": once a week it re-reads recent notes and asks the model
to extract AT MOST 3 lessons that are grounded in REAL SIGNAL (a corrected mistake, a pattern
seen 2+ times, a tool that failed or worked). The hard rule is fail-closed: NO signal => NO
lesson. It never invents one to look busy. Two gates enforce that:

  1. Too few notes to reason over (< 3) -> return early, store nothing.
  2. The model is told to output exactly "NONE" when there is nothing worth keeping -> on NONE
     (or empty, or a model error) we store nothing.

Anything that survives both gates is appended to persistent memory via agent.memory.add(...,
kind='lesson'), so it shows up in future recall/digests. Stdlib only; the model config is the
agent's PRIMARY model (cfg['model']) built with agent.llm.config_from_dict.

Run weekly via systemd/ai-employee-reflect.timer (`python -m agent reflect`, Sunday ~22:00).
"""
from __future__ import annotations

from . import llm, memory

# Below this many total notes there is not enough to reason over -> fail closed.
_MIN_NOTES = 3
# Hard cap on stored lessons, matching the prompt's "AT MOST 3".
_MAX_LESSONS = 3

_PROMPT = (
    "From these notes, distill AT MOST 3 durable lessons drawn ONLY from real signal "
    "(a corrected mistake, a pattern repeated 2+ times, a tool that failed/worked). "
    "If there is no such signal, output exactly: NONE\n\n"
    "Output one lesson per line, no numbering, no preamble.\n\n"
    "Notes:\n{notes}"
)


def _fmt_notes(notes: list[dict]) -> str:
    lines = []
    for r in notes:
        lines.append(f"({r.get('kind', 'note')}) {r.get('text', '')}".strip())
    return "\n".join(lines)


def _parse_lessons(reply: str) -> list[str]:
    """Split the model reply into lesson strings. 'NONE'/empty -> []. Caps at _MAX_LESSONS."""
    reply = (reply or "").strip()
    if not reply or reply.strip().upper() == "NONE":
        return []
    out = []
    for line in reply.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line:
            continue
        if line.upper() == "NONE":          # a stray NONE among blanks -> still nothing
            continue
        out.append(line)
    return out[:_MAX_LESSONS]


def reflect(cfg: dict, logger=print) -> str:
    """Distil durable lessons from recent memory and store them. Fail-closed.

    Returns a short status string (also useful for the systemd journal). Stores nothing
    when there is no signal, when the model says NONE, or when the model errors.
    """
    cfg = cfg or {}
    notes = memory.recent(50)
    if len(notes) < _MIN_NOTES:
        logger("reflect: no signal -> no lesson")
        return "no signal -> no lesson"

    model_cfg = llm.config_from_dict(cfg.get("model", {}))
    prompt = _PROMPT.format(notes=_fmt_notes(notes))
    try:
        out = llm.complete(model_cfg, [{"role": "user", "content": prompt}])
    except llm.LLMError as e:               # model down / no key / bad response -> store nothing
        logger(f"reflect: model error, stored nothing: {e}")
        return f"model error: {e}"

    lessons = _parse_lessons(out.get("content", ""))
    if not lessons:
        logger("reflect: model found no durable lesson (NONE) -> stored nothing")
        return "no lesson (NONE)"

    for lesson in lessons:
        memory.add(lesson, kind="lesson")
    logger(f"reflect: stored {len(lessons)} lesson(s)")
    return f"stored {len(lessons)} lesson(s)"
