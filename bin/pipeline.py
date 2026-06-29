#!/usr/bin/env python3
"""daily pipeline: intake inbox records -> CRM, regenerate brief.json, stamp the run.
Fully deterministic (no LLM, zero model quota). flock guards against double cron runs.
This is the digest pattern: it pre-computes brief.json so the agent reads a digest instead
of gathering data live through expensive model turns."""
import json, os, sys, subprocess, glob, fcntl, shutil, sqlite3, time
from datetime import datetime, timezone, timedelta

H = os.path.expanduser("~/.hermes")
PY = os.path.join(H, "tools-venv/bin/python")
CRMPY = os.path.join(H, "bin/crm.py")
EXPORT = os.path.join(H, "export")
INBOX = os.path.join(EXPORT, "inbox")
DONE = os.path.join(INBOX, "done")
LOCK = os.path.join(H, "data/pipeline.lock")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def crm(*args):
    r = subprocess.run([PY, CRMPY] + [str(x) for x in args], capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except Exception:
        return {"ok": False, "raw": r.stdout, "err": r.stderr}


def weekly():
    counts = {"nurtured": 0, "errors": []}
    dbp = os.path.join(H, "data/leads.db")
    if os.path.exists(dbp):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cx = sqlite3.connect(dbp)
        stale = [r[0] for r in cx.execute("SELECT domain FROM prospect WHERE status='contacted' AND updated_at < ?", (cutoff,))]
        cx.close()
        wk = datetime.now(timezone.utc).strftime("%Y%W")
        for dom in stale:
            crm("status", "--domain", dom, "--to", "nurture", "--note", "21d no reply -> nurture", "-k", "nurture-" + dom + "-" + wk)
            counts["nurtured"] += 1
        try:
            cx = sqlite3.connect(dbp); cx.execute("VACUUM"); cx.close()
        except Exception as e:
            counts["errors"].append("vacuum: " + str(e))
    crm("brief", "--out", os.path.join(EXPORT, "brief.json"))
    stamp = {"ok": not counts["errors"], "mode": "weekly", "finished": now(), "counts": counts}
    with open(os.path.join(EXPORT, "pipeline.run.json"), "w") as fh:
        json.dump(stamp, fh, ensure_ascii=False, indent=1)
    print(json.dumps(stamp, ensure_ascii=False))


def run(mode):
    if mode == "weekly":
        return weekly()
    os.makedirs(DONE, exist_ok=True)
    counts = {"intake": 0, "errors": []}
    for f in sorted(glob.glob(os.path.join(INBOX, "*.json"))):
        try:
            payload = json.load(open(f))
            p = payload.get("prospect", payload)
            crm("log",
                "--domain", p["domain"],
                "--name", p.get("business_name") or p.get("name") or p["domain"],
                "--email", p.get("email") or "",
                "--phone", p.get("phone") or "",
                "--sector", p.get("sector") or "",
                "--source", payload.get("source", "inbox"))
            counts["intake"] += 1
            shutil.move(f, os.path.join(DONE, os.path.basename(f)))
        except Exception as e:
            counts["errors"].append(os.path.basename(f) + ": " + str(e))
    # ENRICH: measure new records without a score (deterministic, rate-limited, max 15/run)
    counts["enriched"] = 0
    dbp = os.path.join(H, "data/leads.db")
    if os.path.exists(dbp):
        cx = sqlite3.connect(dbp)
        todo = [r[0] for r in cx.execute("SELECT domain FROM prospect WHERE status='new' AND weakness_score IS NULL LIMIT 15")]
        cx.close()
        for dom in todo:
            try:
                r = subprocess.run([PY, os.path.join(H, "bin/enrich.py"), dom], capture_output=True, text=True, timeout=60)
                if r.returncode == 0:
                    counts["enriched"] += 1
                else:
                    counts["errors"].append("enrich " + dom + ": exit " + str(r.returncode) + " " + (r.stderr or "")[:120])
                time.sleep(2)
            except Exception as e:
                counts["errors"].append("enrich " + dom + ": " + str(e))
    crm("brief", "--out", os.path.join(EXPORT, "brief.json"))
    stamp = {"ok": not counts["errors"], "mode": mode, "finished": now(), "counts": counts}
    with open(os.path.join(EXPORT, "pipeline.run.json"), "w") as fh:
        json.dump(stamp, fh, ensure_ascii=False, indent=1)
    print(json.dumps(stamp, ensure_ascii=False))


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"ok": True, "status": "skipped_locked"}))
        sys.exit(0)
    run(sys.argv[1] if len(sys.argv) > 1 else "daily")
