#!/usr/bin/env python3
"""dossier - deterministic target research: site measurement + whois + mail provider + web presence.
No LLM (zero quota). Outputs JSON; the web-operator skill turns it into a readable dossier."""
import subprocess, json, os, sys, re
from datetime import datetime, timezone

H = os.path.expanduser("~/.hermes")
PY = os.path.join(H, "tools-venv/bin/python")


def run(cmd, timeout=25):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def whois_info(domain):
    r = run(["whois", domain])
    out = (r.stdout if r else "") or ""

    def find(pat):
        m = re.search(pat, out, re.I)
        return m.group(1).strip() if m else None
    return {
        "registrar": find(r"Registrar:\s*(.+)"),
        "created": find(r"(?:Creation Date|Registered on|Registration Date|created):\s*(.+)"),
        "expires": find(r"(?:Expir\w+ Date|Registry Expiry|paid-till):\s*(.+)"),
    }


def mail_provider(domain):
    r = run(["dig", "+short", "MX", domain])
    out = (r.stdout if r else "").lower()
    if "google" in out or "googlemail" in out:
        return "Google Workspace"
    if "outlook" in out or "microsoft" in out or "office365" in out:
        return "Microsoft 365"
    if "mailprotect" in out or "combell" in out or "one.com" in out:
        return "regional host (Combell/One)"
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    # RFC 7505 "null MX" (a bare "." or "0 .") means the domain explicitly accepts no mail
    if not lines or all(l in (".", "0 .") or l.endswith(" .") for l in lines):
        return "none"
    return lines[0]


def web_presence(query, n=5):
    try:
        from ddgs import DDGS
        with DDGS() as d:
            return [{"title": r.get("title"), "url": r.get("href")} for r in d.text(query, max_results=n)]
    except Exception as e:
        return [{"error": str(e)}]


def site_audit(domain):
    r = run([PY, os.path.join(H, "bin/enrich.py"), domain, "--no-write"], timeout=60)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: dossier.py <domain> [--name 'Name']"}))
        sys.exit(1)
    domain = re.sub(r"^www\.", "", re.sub(r"^https?://", "", sys.argv[1].strip().lower()).split("/")[0])
    name = None
    if "--name" in sys.argv:
        i = sys.argv.index("--name")
        if i + 1 < len(sys.argv):
            name = sys.argv[i + 1]
    audit = site_audit(domain)
    dossier = {
        "schema": "dossier/v1",
        "domain": domain,
        "name": name or domain,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site": {
            "weakness_score": audit.get("weakness_score"),
            "reasons": audit.get("weakness_reasons"),
            "signals": audit.get("signals"),
        },
        "domain_info": whois_info(domain),
        "mail_provider": mail_provider(domain),
        "web_presence": web_presence((name or domain), 5),
    }
    print(json.dumps(dossier, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
