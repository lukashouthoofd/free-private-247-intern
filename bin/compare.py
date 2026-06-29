#!/usr/bin/env python3
"""compare - rank multiple sites by web weakness -> ranking (which is the best lead).
Pass domains or --search 'sector place' (ddgs finds candidates). Deterministic, zero quota."""
import subprocess, json, os, sys, re, time

H = os.path.expanduser("~/.hermes")
PY = os.path.join(H, "tools-venv/bin/python")
DIRECTORIES = ("facebook.", "instagram.", "handelsgids.", "goudengids.", "linkedin.",
               "tripadvisor.", "google.", "youtube.", "trustpilot.", "wikipedia.", "deweekvan.")


def ndom(u):
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", (u or "").strip().lower()).split("/")[0])


def enrich(domain):
    r = subprocess.run([PY, os.path.join(H, "bin/enrich.py"), domain, "--no-write"], capture_output=True, text=True, timeout=70)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def search_domains(query, n=14):
    try:
        from ddgs import DDGS
        out = []
        with DDGS() as d:
            for r in d.text(query, max_results=n):
                dom = ndom(r.get("href", ""))
                if dom and "." in dom and not any(x in dom for x in DIRECTORIES) and dom not in out:
                    out.append(dom)
        return out
    except Exception:
        return []


def main():
    args = sys.argv[1:]
    domains = []
    if "--search" in args:
        i = args.index("--search")
        q = args[i + 1] if i + 1 < len(args) else ""
        domains = search_domains(q)[:6]
    domains += [ndom(a) for a in args if "." in a and not a.startswith("--")]
    domains = list(dict.fromkeys([d for d in domains if d]))[:6]
    if not domains:
        print(json.dumps({"ok": False, "error": "pass domains, or --search 'sector place'"}))
        sys.exit(1)
    rows = []
    for dom in domains:
        a = enrich(dom)
        sig = a.get("signals", {})
        rows.append({"domain": dom, "score": a.get("weakness_score"),
                     "top_reason": (a.get("weakness_reasons") or ["-"])[0],
                     "load_ms": sig.get("load_ms"), "https": sig.get("https_redirect")})
        time.sleep(2)
    rows.sort(key=lambda r: (r["score"] if r["score"] is not None else -1), reverse=True)
    print(json.dumps({"ok": True, "ranked": rows, "best_lead": rows[0] if rows else None}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
