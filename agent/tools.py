"""
Built-in tools. Each is a Tool(name, description, json-schema, fn, gate).
Tools return a string the model reads. The loop catches exceptions, but keep them defensive.
Add your own and append to DEFAULT_TOOLS (or build a domain pack, e.g. the website-verifier).
Gates: read/measure = autonomous; anything that writes or runs commands = ask_first.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .loop import Tool

_UA = "self-hosted-ai-employee/0.1 (+https://github.com/)"


def _is_safe_url(url: str) -> bool:
    """Refuse SSRF targets: userinfo bypass + internal/loopback/metadata IPs. DNS/parse error -> refuse."""
    try:
        parts = urlsplit(url)
        if "@" in parts.netloc:  # userinfo bypass (http://trusted@169.254.169.254/)
            return False
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        for sa in socket.getaddrinfo(host, port):
            ip = ipaddress.ip_address(sa[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                    or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Re-validate every 3xx target so a public URL cannot 302 into an internal host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_safe_url(newurl):
            raise urllib.error.URLError("blocked redirect to internal address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect())

_SECRET_SUFFIXES = (".env", ".key", ".pem", ".p12", ".pfx", ".crt", ".cer")
_SECRET_SUBSTRINGS = ("secret", "credential", "token", "password", "id_rsa", "id_ed25519")
_SECRET_DIRS = {"secrets", "identity"}
_SECRET_PATTERNS = ("API_KEY", "TOKEN", "SECRET", "CREDENTIAL", "PASSWORD", "_KEY")


def _scrub_env() -> dict[str, str]:
    """Child env without secrets (keeps PATH/HOME/LANG) so an approved shell can't exfiltrate tokens."""
    return {k: v for k, v in os.environ.items() if not any(p in k.upper() for p in _SECRET_PATTERNS)}


def _web_fetch(args: dict) -> str:
    url = (args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return "ERROR: url must start with http:// or https://"
    if not _is_safe_url(url):
        return "ERROR: refusing to fetch internal/loopback/metadata address"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
        with _OPENER.open(req, timeout=20) as r:
            return r.read(200_000).decode("utf-8", "replace")[:8000]
    except Exception as e:
        return f"ERROR fetching {url}: {e}"


def _read_file(args: dict) -> str:
    raw = args.get("path", "")
    try:
        path = os.path.realpath(os.path.abspath(raw))
    except Exception:
        path = raw
    name = os.path.basename(path).lower()
    parts = {p.lower() for p in path.replace("\\", "/").split("/")}
    if (name == ".env" or name.endswith(_SECRET_SUFFIXES)
            or any(s in name for s in _SECRET_SUBSTRINGS) or (_SECRET_DIRS & parts)):
        return "ERROR: refusing to read a secrets file (.env / keys are off-limits to the agent)"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
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
        p = subprocess.run(cmd, shell=True, env=_scrub_env(), capture_output=True, text=True, timeout=60)
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
