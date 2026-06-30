"""
Persistent memory — an append-only notes log the agent reads and writes itself.

This is the difference between a chatbot (amnesiac every turn) and an employee (remembers
what happened yesterday). Storage is a JSON-Lines file at data/memory/notes.jsonl: one note
per line, append-only, so a crash mid-write can at worst lose the last line, never the file.

Two tools are exported in MEMORY_TOOLS, both gate `autonomous` (storing/reading the agent's
OWN private notes on the operator's own box is not an outward action):
  - remember(text, kind) : append a note
  - recall(query, n)     : recent notes, optionally filtered by substring

The data dir is created lazily on first write; every read tolerates a missing file (returns
empty) so the agent never crashes on a fresh install.
"""
from __future__ import annotations

import json
import os
import time

from .loop import Tool

# Resolve the memory dir from MEMORY_DIR (set by the caller/config) or fall back to ./data/memory.
# Kept as a function so tests can monkeypatch the env var per-tempdir.
_DEFAULT_DIR = os.path.join("data", "memory")


def _dir() -> str:
    return os.environ.get("MEMORY_DIR", _DEFAULT_DIR)


def _path() -> str:
    return os.path.join(_dir(), "notes.jsonl")


def add(text: str, kind: str = "note") -> dict:
    """Append a note. Returns the stored record. Creates the dir lazily; never raises on a clean box."""
    text = (text or "").strip()
    if not text:
        return {}
    rec = {"ts": time.time(), "kind": (kind or "note").strip() or "note", "text": text}
    os.makedirs(_dir(), exist_ok=True)
    with open(_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _all() -> list[dict]:
    """Read every note. Missing file -> []. Bad lines are skipped, not fatal."""
    path = _path()
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def recent(n: int = 20) -> list[dict]:
    """The last n notes, oldest-first within the window."""
    notes = _all()
    if n <= 0:
        return []
    return notes[-n:]


def search(substr: str) -> list[dict]:
    """All notes whose text or kind contains substr (case-insensitive)."""
    q = (substr or "").strip().lower()
    if not q:
        return []
    return [r for r in _all() if q in (r.get("text", "") + " " + r.get("kind", "")).lower()]


def _fmt(rec: dict) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(rec.get("ts", 0)))
    return f"[{when}] ({rec.get('kind', 'note')}) {rec.get('text', '')}"


def _remember(args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "ERROR: need text to remember"
    rec = add(text, args.get("kind", "note"))
    return f"remembered: {_fmt(rec)}" if rec else "ERROR: nothing stored (empty text)"


def _recall(args: dict) -> str:
    query = (args.get("query") or "").strip()
    try:
        n = int(args.get("n", 20))
    except (TypeError, ValueError):
        n = 20
    hits = search(query) if query else recent(n)
    if query and n > 0:
        hits = hits[-n:]
    if not hits:
        return "(no matching notes)" if query else "(memory is empty)"
    return "\n".join(_fmt(r) for r in hits)


MEMORY_TOOLS = [
    Tool("remember",
         "Save a short note to your persistent memory so you recall it in future sessions "
         "(facts about the operator, decisions, ongoing tasks). Read-only to the outside world.",
         {"type": "object",
          "properties": {"text": {"type": "string", "description": "the note to store"},
                         "kind": {"type": "string",
                                  "description": "optional tag, e.g. fact|task|decision|note"}},
          "required": ["text"]},
         _remember, "autonomous"),
    Tool("recall",
         "Retrieve your persistent notes. With 'query' it substring-searches; without one it "
         "returns the most recent notes (n).",
         {"type": "object",
          "properties": {"query": {"type": "string", "description": "optional substring filter"},
                         "n": {"type": "integer", "description": "how many recent notes (default 20)"}}},
         _recall, "autonomous"),
]
