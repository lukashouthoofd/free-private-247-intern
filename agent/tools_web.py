"""
Example domain tool pack: `verify_website` — does a local business have its OWN website?

A deterministic check (no LLM, can't hallucinate): guess likely .be/.com domains from the
name, fetch them, and confirm the live page is really that business (name tokens in the
<title>/body, plus the town; reject parked "domain for sale" pages). A generic .com must be
corroborated by the town. If nothing is proven, it returns UNCERTAIN — it never *claims*
"no website" (reliably confirming absence needs a real search API; see README).

This shows the pattern: wrap real work in a deterministic tool so the model orchestrates but
the facts are measured. Register it by importing WEB_TOOLS (the CLI already does).
"""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .loop import Tool

_UA = "self-hosted-ai-employee/0.1"


def _host_is_internal(host: str) -> bool:
    """True if the host resolves to any private/loopback/link-local/reserved/metadata IP.
    DNS/parse failure -> treated as internal (fail closed)."""
    if not host:
        return True
    try:
        for *_, (addr, *__) in socket.getaddrinfo(host, None):
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                    or ip.is_multicast or ip.is_unspecified):
                return True
        return False
    except Exception:
        return True


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Re-validate every 3xx target so a guessed public domain cannot 302 into an internal
    host (cloud metadata, 10.x, 127.x). urlopen follows redirects silently otherwise."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlsplit(newurl)
        # http(s) only, no userinfo bypass (http://public@169.254.169.254/), host must resolve public
        if (p.scheme not in ("http", "https") or "@" in p.netloc
                or _host_is_internal(p.hostname or "")):
            raise urllib.error.URLError("blocked redirect to internal address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# A module-local opener (NOT a global install_opener) so redirect validation stays scoped to
# verify_website and never mutates urllib for the rest of the process (llm.py, telegram.py, ...).
_SSRF_OPENER = urllib.request.build_opener(_SafeRedirect())

_DIRECTORY = re.compile(r"(^|\.)(facebook|instagram|linkedin|goudengids|goldenpages|tripadvisor|"
                        r"resengo|joyn|deliveroo|ubereats|takeaway|yelp|google\.|maps\.|sitew\.|"
                        r"wixsite|jimdo|one\.com|trustpilot|booking)\.", re.I)
_DIRECTORY_ONECOM = re.compile(r"(^|\.)one\.com$", re.I)
_PARKED = re.compile(r"(domain (is|may be) for sale|premium domain|domain for sale|parkingcrew|"
                     r"website coming soon|under construction|te koop)", re.I)
_STOP = {"de", "het", "een", "en", "van", "bakkerij", "slagerij", "kapsalon", "restaurant",
         "cafe", "frituur", "salon", "shop", "winkel", "patisserie", "traiteur", "bv", "bvba"}


def _strip(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower())


def _tokens(name: str):
    return [w for w in _strip(name).split() if len(w) >= 3 and w not in _STOP]


def _host(u: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", u, re.I)
    return (m.group(1) if m else "").lower()


def _candidates(name: str, town: str):
    full = re.sub(r"[^a-z0-9]", "", _strip(name).replace(" ", ""))
    toks = _tokens(name)
    brand = max((t for t in toks if len(t) >= 4), key=len, default=None) or (full if len(full) >= 4 else None)
    out = []
    for base in dict.fromkeys([full, brand]):
        if base:
            out += [base + ".be", base + ".com"]
    return out[:6]


def _fetch(url: str):
    try:
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or "@" in p.netloc or _host_is_internal(p.hostname or ""):
            return None, None  # block SSRF to internal hosts (redirects re-checked by _SafeRedirect)
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with _SSRF_OPENER.open(req, timeout=9) as r:      # redirects re-validated by _SafeRedirect
            final = r.geturl()
            html = r.read(120_000).decode("utf-8", "replace")
        return final, html
    except Exception:
        return None, None


def _owns(html: str, name: str, town: str, strict: bool) -> bool:
    title = _strip(" ".join(re.findall(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)[:1]
                            + re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)[:1]))
    body = _strip(re.sub(r"<[^>]+>", " ", html))[:20000]
    if _PARKED.search(title) or _PARKED.search(body[:2000]):
        return False
    toks = _tokens(name)
    if not toks:
        return False
    name_in_body = sum(t in body for t in toks)
    name_in_title = any(t in title for t in toks)
    t = _strip(town).strip() if town else ""   # whole town (handles "De Pinte" etc.)
    town_hit = len(t) >= 4 and t in (title + " " + body)
    if strict:
        return (name_in_title or name_in_body >= 1) and town_hit
    if name_in_body >= 2:
        return True
    if (name_in_body >= 1 or name_in_title) and town_hit:
        return True
    return False


def _verify_website(args: dict) -> str:
    name = (args.get("name") or "").strip()
    town = (args.get("town") or "").strip()
    if not name:
        return "ERROR: need a business name"
    for cand in _candidates(name, town):
        if _DIRECTORY.search(cand) or _DIRECTORY_ONECOM.search(cand):
            continue
        final, html = _fetch("https://" + cand)
        if not html or _DIRECTORY.search(_host(final or "")) or _DIRECTORY_ONECOM.search(_host(final or "")):
            continue
        if _host(final or "").split(".")[-2:] != cand.split(".")[-2:]:
            continue  # redirected off the guessed domain
        if _owns(html, name, town, strict=cand.endswith(".com")):
            return f"HAS_SITE: {name} -> {final}"
    return (f"UNCERTAIN: no own-domain website proven for '{name}'"
            f"{' in ' + town if town else ''} via domain-guess. "
            f"It may have none, or a differently-named domain (a search-API key would confirm).")


WEB_TOOLS = [
    Tool("verify_website",
         "Check whether a local business has its OWN website (deterministic domain-guess + page "
         "ownership check). Returns HAS_SITE with the URL, or UNCERTAIN. Never falsely claims 'no site'.",
         {"type": "object",
          "properties": {"name": {"type": "string", "description": "business name"},
                         "town": {"type": "string", "description": "town/city (improves accuracy)"}},
          "required": ["name"]},
         _verify_website, "autonomous"),
]
