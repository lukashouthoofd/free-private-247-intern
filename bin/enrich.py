#!/usr/bin/env python3
"""enrich - measure a website deterministically (curl/openssl/whatweb) -> weakness_score in the CRM.
Fully deterministic (no LLM, zero quota). A reproducible score, not a guess."""
import subprocess, json, os, sys, re, ssl, socket
from datetime import datetime, timezone

H = os.path.expanduser("~/.hermes")
PY = os.path.join(H, "tools-venv/bin/python")
CRMPY = os.path.join(H, "bin/crm.py")


def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def cert_days(domain):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=8) as s:
            with ctx.wrap_socket(s, server_hostname=domain) as ss:
                cert = ss.getpeercert()
        exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return (exp - datetime.now(timezone.utc)).days
    except Exception:
        return None


def measure(domain):
    url = "https://" + domain
    sig = {}
    r = run(["curl", "-sSIL", "--max-time", "12", url])
    hdr = (r.stdout if r else "") or ""
    hl = hdr.lower()
    st = re.findall(r"http/[\d.]+\s+(\d{3})", hl)
    sig["http_status"] = int(st[-1]) if st else 0
    sig["hsts"] = "strict-transport-security" in hl
    rh = run(["curl", "-sSI", "--max-time", "10", "http://" + domain])
    httph = (rh.stdout if rh else "").lower()
    sig["https_redirect"] = ("location: https" in httph) or (sig["http_status"] in (200, 301, 302) and "https" in hl)
    rt = run(["curl", "-so", "/dev/null", "-w", "%{time_total}", "--max-time", "15", url])
    try:
        sig["load_ms"] = int(float(rt.stdout) * 1000) if rt and rt.stdout.strip() else None
    except Exception:
        sig["load_ms"] = None
    sig["cert_days_left"] = cert_days(domain)
    rw = run(["whatweb", "-q", "--color=never", url], timeout=20)
    ww = rw.stdout if rw else ""
    found = re.findall(r"(WordPress|Wix|Weebly|Jimdo|Squarespace|Shopify|Drupal|Joomla)", ww, re.I)
    srv = re.search(r"server:\s*(.+)", hl)
    server = srv.group(1).strip() if srv else ""
    if not found and "pepyaka" in server.lower():
        found = ["Wix"]  # pepyaka = Wix' nginx signature
    sig["generator"] = (",".join(sorted(set(found))) if found else server)
    body = run(["curl", "-sL", "--max-time", "12", url], timeout=15)
    html = (body.stdout if body else "")[:200000].lower()
    sig["mobile_viewport"] = ('name="viewport"' in html) or ("name='viewport'" in html)
    return sig


def score(sig):
    s, reasons = 0, []
    if sig.get("https_redirect") is False or sig.get("http_status", 0) == 0:
        s += 30; reasons.append("no HTTPS redirect or site unreachable")
    cd = sig.get("cert_days_left")
    if cd is not None and cd < 0:
        s += 25; reasons.append("TLS certificate expired (" + str(cd) + "d)")
    elif cd is not None and cd < 14:
        s += 10; reasons.append("TLS cert expiring soon (" + str(cd) + "d)")
    lm = sig.get("load_ms")
    if lm is not None and lm > 4000:
        s += 20; reasons.append("very slow (" + str(lm) + "ms)")
    elif lm is not None and lm > 2500:
        s += 12; reasons.append("slow load time (" + str(lm) + "ms)")
    if sig.get("mobile_viewport") is False:
        s += 10; reasons.append("no mobile viewport meta")
    g = (sig.get("generator") or "").lower()
    if any(x in g for x in ["wix", "weebly", "jimdo", "godaddy"]):
        s += 10; reasons.append("vendor-locked platform (" + sig.get("generator", "") + ")")
    if not sig.get("hsts"):
        s += 5; reasons.append("no HSTS")
    return max(0, min(100, s)), reasons


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: enrich.py <domain> [--no-write]"})); sys.exit(1)
    domain = re.sub(r"^www\.", "", re.sub(r"^https?://", "", sys.argv[1].strip().lower()).split("/")[0])
    sig = measure(domain)
    sc, reasons = score(sig)
    audit = {"schema": "site_audit/v1", "domain": domain,
             "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "signals": sig, "weakness_score": sc, "weakness_reasons": reasons}
    if "--no-write" not in sys.argv:
        subprocess.run([PY, CRMPY, "enrich", "--domain", domain, "--score", str(sc), "--json", json.dumps(audit, ensure_ascii=False)],
                       capture_output=True, text=True)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
