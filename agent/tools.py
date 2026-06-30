"""
Built-in tools. Each is a Tool(name, description, json-schema, fn, gate).
Tools return a string the model reads. The loop catches exceptions, but keep them defensive.
Add your own and append to DEFAULT_TOOLS (or build a domain pack, e.g. the website-verifier).
Gates: read/measure = autonomous; anything that writes or runs commands = ask_first.
"""
from __future__ import annotations

import subprocess
import urllib.request

from .loop import Tool

_UA = "self-hosted-ai-employee/0.1 (+https://github.com/)"


def _web_fetch(args: dict) -> str:
    url = (args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return "ERROR: url must start with http:// or https://"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(200_000).decode("utf-8", "replace")[:8000]
    except Exception as e:
        return f"ERROR fetching {url}: {e}"


def _read_file(args: dict) -> str:
    try:
        with open(args.get("path", ""), "r", encoding="utf-8", errors="replace") as f:
            return f.read(8000)
    except Exception as e:
        return f"ERROR: {e}"


def _write_file(args: dict) -> str:
    path, content = args.get("path", ""), args.get("content", "")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR: {e}"


def _run_shell(args: dict) -> str:
    cmd = args.get("command", "")
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return (p.stdout + p.stderr)[:8000] or f"(exit {p.returncode}, no output)"
    except Exception as e:
        return f"ERROR: {e}"


DEFAULT_TOOLS = [
    Tool("web_fetch", "Fetch a public URL and return its text (truncated). Read-only.",
         {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
         _web_fetch, "autonomous"),
    Tool("read_file", "Read a local file (truncated).",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
         _read_file, "autonomous"),
    Tool("write_file", "Write text to a local file (overwrites). Needs operator approval.",
         {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
          "required": ["path", "content"]},
         _write_file, "ask_first"),
    Tool("run_shell", "Run a shell command on the box. Needs operator approval.",
         {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
         _run_shell, "ask_first"),
]
