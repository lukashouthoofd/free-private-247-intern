"""
Built-in tools. Each is a Tool(name, description, json-schema, fn, gate).
Tools return a string the model reads. The loop catches exceptions, but keep them defensive.
Add your own and append to DEFAULT_TOOLS (or build a domain pack, e.g. the website-verifier).

Safety posture (the defaults a non-expert inherits):
  - web_fetch : autonomous, but SSRF-guarded (no loopback/private/link-local/metadata, and every
                redirect is re-validated so a public URL can't 302 into an internal host)
  - read_file : autonomous, but refuses secrets (.env / keys / token/credential paths)
  - write_file: ask_first, AND jailed to the agent's working dir (no escaping it)
  - run_shell : OFF by default. Opt in with  tools.run_shell.enabled: true  in config.yaml. When on
                it is ask_first, runs an argv list (no shell — metacharacters can't chain a second
                command), and the child env is scrubbed of API keys/tokens.
"""
from __future__ import annotations

import ipaddress
import os
import shlex
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


def _workdir_root() -> str:
    """The only tree write_file is allowed to touch. Defaults to the process CWD (the repo dir
    under systemd's WorkingDirectory); override with AGENT_WORKDIR for a custom data dir."""
    return os.path.realpath(os.environ.get("AGENT_WORKDIR") or os.getcwd())


def _within_workdir(path: str) -> bool:
    # realpath resolves `..` and symlinks, so `data/evil -> /etc` or `../../etc` can't escape.
    root = _workdir_root()
    target = os.path.realpath(path)
    return target == root or target.startswith(root + os.sep)


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
    if not path:
        return "ERROR: path is required"
    if not _within_workdir(path):
        return (f"ERROR: refused — write_file is jailed to the working directory ({_workdir_root()}); "
                f"'{path}' is outside it. Write under the working dir (e.g. data/...).")
    try:
        target = os.path.realpath(path)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR: {e}"


def _run_shell(args: dict) -> str:
    # No shell=True: split into an argv list so shell metacharacters (`;`, `|`, `$()`, `&&`,
    # redirects, globs) are inert — the model can't chain a second command past the approved one.
    # The child env is still scrubbed of secrets (defense in depth for an approved command).
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return "ERROR: command is required"
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return f"ERROR: could not parse command ({e})"
    if not argv:
        return "ERROR: empty command"
    try:
        p = subprocess.run(argv, env=_scrub_env(), capture_output=True, text=True, timeout=60)
        return (p.stdout + p.stderr)[:8000] or f"(exit {p.returncode}, no output)"
    except FileNotFoundError:
        return f"ERROR: command not found: {argv[0]}"
    except Exception as e:
        return f"ERROR: {e}"


# Always-on, safe-by-default tools.
DEFAULT_TOOLS = [
    Tool("web_fetch", "Fetch a public URL and return its text (truncated). Read-only.",
         {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
         _web_fetch, "autonomous"),
    Tool("read_file", "Read a local file (truncated).",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
         _read_file, "autonomous"),
    Tool("write_file", "Write text to a local file under the agent's working dir (overwrites). "
                       "Needs operator approval.",
         {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
          "required": ["path", "content"]},
         _write_file, "ask_first"),
]

# Opt-in only: arbitrary command execution. Registered solely when config enables it.
RUN_SHELL_TOOL = Tool(
    "run_shell", "Run a command on the box as an argv list (no shell). Needs operator approval.",
    {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    _run_shell, "ask_first")


def _truthy(v) -> bool:
    """Strict opt-in test. A QUOTED yaml value (`enabled: 'false'`) loads as the string
    'false', and bool('false') is True — so we must not lean on bool(). Only a real boolean
    True, or an explicit affirmative string/number, enables a powerful tool."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(v, (int, float)):
        return v != 0
    return False


def build_default_tools(cfg: dict | None = None) -> list[Tool]:
    """The safe default toolset, plus run_shell ONLY if the operator opted in via
    `tools.run_shell.enabled: true` in config.yaml. Off by default."""
    tools = list(DEFAULT_TOOLS)
    if _truthy((((cfg or {}).get("tools") or {}).get("run_shell") or {}).get("enabled", False)):
        tools.append(RUN_SHELL_TOOL)
    return tools
