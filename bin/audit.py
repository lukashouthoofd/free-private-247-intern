#!/usr/bin/env python3
"""audit - a client-ready website-audit PDF from a deterministic measurement (enrich). Zero quota."""
import subprocess, json, os, sys, re
from datetime import datetime

H = os.path.expanduser("~/.hermes")
PY = os.path.join(H, "tools-venv/bin/python")
OUT = os.path.join(H, "export/out")


def enrich(domain):
    r = subprocess.run([PY, os.path.join(H, "bin/enrich.py"), domain, "--no-write"], capture_output=True, text=True, timeout=70)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"signals": {}, "weakness_score": None, "weakness_reasons": []}


def render(domain, name, a):
    s = a.get("signals", {})
    score = a.get("weakness_score") or 0
    reasons = a.get("weakness_reasons") or []
    cd = s.get("cert_days_left")
    lm = s.get("load_ms")
    checks = [
        ("HTTPS / security", "OK" if s.get("https_redirect") else "Problem", bool(s.get("https_redirect"))),
        ("SSL certificate", (str(cd) + " days valid") if cd is not None else "unknown", (cd or 0) > 14),
        ("Load time", (str(lm) + " ms") if lm else "unknown", (lm or 9999) < 2500),
        ("Mobile", "OK" if s.get("mobile_viewport") else "Not mobile-ready", bool(s.get("mobile_viewport"))),
        ("HSTS security", "OK" if s.get("hsts") else "Missing", bool(s.get("hsts"))),
        ("Platform", s.get("generator") or "unknown", True),
    ]
    rows = ""
    for label, val, ok in checks:
        color = "#1a7f37" if ok else "#cf222e"
        rows += '<tr><td>' + label + '</td><td style="color:' + color + ';font-weight:600">' + val + '</td></tr>'
    reasons_html = "".join("<li>" + r + "</li>" for r in reasons) or "<li>No major technical issues found.</li>"
    scolor = "#cf222e" if score >= 40 else ("#bf8700" if score >= 15 else "#1a7f37")
    return ('<!doctype html><html><head><meta charset="utf-8"><style>'
            'body{font-family:Segoe UI,Roboto,Helvetica,sans-serif;color:#1c2024;margin:0;padding:40px;font-size:13px}'
            'h1{color:#0d1b2a;font-size:22px;margin:0}h3{color:#0d1b2a;margin-top:22px}'
            '.sub{color:#666;margin:4px 0 22px}'
            '.score{font-size:40px;font-weight:700;color:' + scolor + '}'
            'table{width:100%;border-collapse:collapse;margin:14px 0}td{padding:8px 10px;border-bottom:1px solid #eee}'
            '.cta{background:#f3f6fb;padding:14px 16px;border-radius:8px;margin-top:20px}'
            '.foot{margin-top:28px;color:#666;font-size:11px;border-top:1px solid #eee;padding-top:12px}'
            '</style></head><body>'
            '<h1>Website audit &mdash; ' + name + '</h1>'
            '<div class="sub">' + domain + ' &middot; ' + datetime.now().strftime("%d/%m/%Y") + ' &middot; YOUR COMPANY</div>'
            '<p>Improvement score: <span class="score">' + str(score) + '/100</span> '
            '<span style="color:#666">(higher = more to gain)</span></p>'
            '<h3>Measurements</h3><table>' + rows + '</table>'
            '<h3>Top improvement points</h3><ul>' + reasons_html + '</ul>'
            '<div class="cta"><b>Next step</b><br>Want to know what this costs you in visitors and how to fix it? '
            'A no-obligation analysis + proposal.</div>'
            '<div class="foot">YOUR NAME &mdash; YOUR COMPANY &mdash; your-domain.dev<br>'
            'Measured on ' + (a.get("measured_at", "") or "") + '. Figures are deterministically measured, not estimated.</div>'
            '</body></html>')


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: audit.py <domain> [--name 'Name']"}))
        sys.exit(1)
    domain = re.sub(r"^www\.", "", re.sub(r"^https?://", "", sys.argv[1].strip().lower()).split("/")[0])
    name = domain
    if "--name" in sys.argv:
        i = sys.argv.index("--name")
        if i + 1 < len(sys.argv):
            name = sys.argv[i + 1]
    a = enrich(domain)
    os.makedirs(OUT, exist_ok=True)
    hp = os.path.join(OUT, "audit-" + domain + ".html")
    pp = os.path.join(OUT, "audit-" + domain + ".pdf")
    with open(hp, "w") as f:
        f.write(render(domain, name, a))
    r = subprocess.run(["weasyprint", hp, pp], capture_output=True, text=True, timeout=60)
    ok = os.path.exists(pp) and os.path.getsize(pp) > 1000
    print(json.dumps({"ok": ok, "pdf": pp, "score": a.get("weakness_score"),
                      "err": (r.stderr[:200] if not ok else None)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
