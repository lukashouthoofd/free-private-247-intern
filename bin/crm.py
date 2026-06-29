#!/usr/bin/env python3
"""crm - a system-of-record for records (e.g. leads). JSON in/out, idempotent writes."""
import argparse, json, sqlite3, sys, os, re
from datetime import datetime, timezone

DB = os.environ.get("CRM_DB", os.path.expanduser("~/.hermes/data/leads.db"))
STATUSES = ["new", "qualified", "contacted", "replied", "meeting", "won", "lost", "nurture"]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ndom(d):
    d = (d or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    return d.split("/")[0]


SCHEMA = """
PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS prospect(
 id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL UNIQUE, business_name TEXT NOT NULL,
 contact_name TEXT, email TEXT, phone TEXT, city TEXT DEFAULT '', sector TEXT,
 status TEXT NOT NULL DEFAULT 'new', weakness_json TEXT, weakness_score INTEGER,
 next_action TEXT, next_action_due TEXT, source TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(status IN ('new','qualified','contacted','replied','meeting','won','lost','nurture')));
CREATE TABLE IF NOT EXISTS note(
 id INTEGER PRIMARY KEY AUTOINCREMENT, prospect_id INTEGER NOT NULL REFERENCES prospect(id) ON DELETE CASCADE,
 kind TEXT NOT NULL DEFAULT 'note', body TEXT, channel TEXT, actor TEXT NOT NULL DEFAULT 'hermes',
 idempotency_key TEXT UNIQUE, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_note_p ON note(prospect_id);
CREATE INDEX IF NOT EXISTS ix_p_status ON prospect(status);
"""


def con():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def emit(ok, command, **kw):
    print(json.dumps({"ok": ok, "command": command, **kw}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def row(r):
    return {k: r[k] for k in r.keys()} if r else None


def c_log(a):
    c = con()
    d = ndom(a.domain)
    t = now()
    ex = c.execute("SELECT * FROM prospect WHERE domain=?", (d,)).fetchone()
    if ex:
        sets, vals = [], []
        for col, val in [("business_name", a.name), ("email", a.email), ("phone", a.phone), ("sector", a.sector), ("contact_name", a.contact)]:
            if val:
                sets.append(col + "=?")
                vals.append(val)
        if sets:
            vals += [t, d]
            c.execute("UPDATE prospect SET " + ",".join(sets) + ",updated_at=? WHERE domain=?", vals)
            c.commit()
        emit(True, "log", status="updated", data=row(c.execute("SELECT * FROM prospect WHERE domain=?", (d,)).fetchone()))
    c.execute("INSERT INTO prospect(domain,business_name,contact_name,email,phone,sector,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (d, a.name, a.contact, a.email, a.phone, a.sector, a.source or "manual", t, t))
    c.commit()
    emit(True, "log", status="created", data=row(c.execute("SELECT * FROM prospect WHERE domain=?", (d,)).fetchone()))


def c_status(a):
    c = con()
    d = ndom(a.domain)
    if a.to not in STATUSES:
        emit(False, "status", error="invalid status")
    p = c.execute("SELECT * FROM prospect WHERE domain=?", (d,)).fetchone()
    if not p:
        emit(False, "status", error="unknown domain " + d)
    if a.idempotency_key and c.execute("SELECT 1 FROM note WHERE idempotency_key=?", (a.idempotency_key,)).fetchone():
        emit(True, "status", status="noop", reason="duplicate_idempotency_key")
    c.execute("UPDATE prospect SET status=?,updated_at=? WHERE domain=?", (a.to, now(), d))
    body = p["status"] + " -> " + a.to + ((": " + a.note) if a.note else "")
    c.execute("INSERT INTO note(prospect_id,kind,body,actor,idempotency_key,created_at) VALUES(?,?,?,?,?,?)",
              (p["id"], "status_change", body, a.actor, a.idempotency_key, now()))
    c.commit()
    emit(True, "status", status="changed", data={"domain": d, "from": p["status"], "to": a.to})


def c_note(a):
    c = con()
    d = ndom(a.domain)
    p = c.execute("SELECT id FROM prospect WHERE domain=?", (d,)).fetchone()
    if not p:
        emit(False, "note", error="unknown domain " + d)
    if a.idempotency_key and c.execute("SELECT 1 FROM note WHERE idempotency_key=?", (a.idempotency_key,)).fetchone():
        emit(True, "note", status="noop", reason="duplicate_idempotency_key")
    c.execute("INSERT INTO note(prospect_id,kind,body,channel,actor,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?)",
              (p["id"], "note", a.body, a.channel, a.actor, a.idempotency_key, now()))
    c.commit()
    emit(True, "note", status="added", data={"domain": d})


def c_action(a):
    c = con()
    d = ndom(a.domain)
    if not c.execute("SELECT 1 FROM prospect WHERE domain=?", (d,)).fetchone():
        emit(False, "action", error="unknown domain " + d)
    c.execute("UPDATE prospect SET next_action=?,next_action_due=?,updated_at=? WHERE domain=?", (a.next, a.due, now(), d))
    c.commit()
    emit(True, "action", status="set", data={"domain": d, "next_action": a.next, "due": a.due})


def c_get(a):
    c = con()
    d = ndom(a.domain)
    p = c.execute("SELECT * FROM prospect WHERE domain=?", (d,)).fetchone()
    if not p:
        emit(False, "get", error="unknown domain " + d)
    notes = [row(n) for n in c.execute("SELECT kind,body,actor,created_at FROM note WHERE prospect_id=? ORDER BY id DESC LIMIT 20", (p["id"],))]
    emit(True, "get", data=row(p), notes=notes)


def c_list(a):
    c = con()
    q = "SELECT * FROM prospect"
    w, v = [], []
    if a.status:
        w.append("status=?")
        v.append(a.status)
    if a.sector:
        w.append("sector LIKE ?")
        v.append("%" + a.sector + "%")
    if w:
        q += " WHERE " + " AND ".join(w)
    q += " ORDER BY weakness_score DESC, updated_at DESC LIMIT ?"
    v.append(a.limit)
    emit(True, "list", data=[row(r) for r in c.execute(q, v)])


def c_hot(a):
    c = con()
    rows = c.execute("SELECT domain,business_name,status,weakness_score,next_action FROM prospect WHERE status IN ('new','qualified') AND weakness_score IS NOT NULL ORDER BY weakness_score DESC LIMIT ?", (a.limit,))
    emit(True, "hot", data=[row(r) for r in rows])


def c_brief(a):
    c = con()
    due = [row(r) for r in c.execute("SELECT domain,business_name,next_action,next_action_due,status FROM prospect WHERE next_action_due IS NOT NULL ORDER BY next_action_due LIMIT 10")]
    hot = [row(r) for r in c.execute("SELECT domain,business_name,weakness_score,status FROM prospect WHERE status IN ('new','qualified') AND weakness_score IS NOT NULL ORDER BY weakness_score DESC LIMIT 5")]
    pipe = dict(c.execute("SELECT status,COUNT(*) FROM prospect GROUP BY status").fetchall())
    data = {"generated_at": now(), "actions_due": due, "hot_leads": hot, "pipeline": pipe}
    if a.out:
        with open(os.path.expanduser(a.out), "w") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
        emit(True, "brief", status="written", path=a.out)
    emit(True, "brief", data=data)


def c_enrich(a):
    c = con()
    d = ndom(a.domain)
    p = c.execute("SELECT * FROM prospect WHERE domain=?", (d,)).fetchone()
    if not p:
        emit(False, "enrich", error="unknown domain " + d)
    score = max(0, min(100, a.score))
    promoted = ""
    if p["status"] == "new" and score >= 40:
        c.execute("UPDATE prospect SET status='qualified' WHERE domain=?", (d,))
        promoted = "qualified"
    c.execute("UPDATE prospect SET weakness_score=?,weakness_json=?,updated_at=? WHERE domain=?",
              (score, a.json or None, now(), d))
    c.commit()
    emit(True, "enrich", status="enriched", data={"domain": d, "weakness_score": score, "promoted": promoted})


def c_health(a):
    c = con()
    emit(True, "health", data={"db": DB, "prospects": c.execute("SELECT COUNT(*) FROM prospect").fetchone()[0]})


P = argparse.ArgumentParser()
S = P.add_subparsers(dest="cmd", required=True)


def add(name, fn, args):
    sp = S.add_parser(name)
    for flags, kw in args:
        sp.add_argument(*flags, **kw)
    sp.set_defaults(fn=fn)


DOM = (("--domain",), {"required": True})
add("log", c_log, [DOM, (("--name",), {"required": True}), (("--contact",), {}), (("--email",), {}), (("--phone",), {}), (("--sector",), {}), (("--source",), {})])
add("status", c_status, [DOM, (("--to",), {"required": True}), (("--note",), {}), (("--actor",), {"default": "hermes"}), (("--idempotency-key", "-k"), {"dest": "idempotency_key"})])
add("note", c_note, [DOM, (("--body",), {"required": True}), (("--channel",), {}), (("--actor",), {"default": "hermes"}), (("--idempotency-key", "-k"), {"dest": "idempotency_key"})])
add("action", c_action, [DOM, (("--next",), {"required": True}), (("--due",), {})])
add("get", c_get, [DOM])
add("list", c_list, [(("--status",), {}), (("--sector",), {}), (("--limit",), {"type": int, "default": 25})])
add("hot", c_hot, [(("--limit",), {"type": int, "default": 5})])
add("brief", c_brief, [(("--out",), {})])
add("enrich", c_enrich, [DOM, (("--score",), {"type": int, "required": True}), (("--json",), {})])
add("health", c_health, [])
a = P.parse_args()
a.fn(a)
