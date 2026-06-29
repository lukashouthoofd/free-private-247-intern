---
name: crm
description: >
  Remember and manage records in a local database via the crm shell command. Use for "log this",
  "what is the status of X", "who to follow up", "set X to contacted", "show my pipeline". Your
  durable MEMORY. A reference implementation of a system-of-record with idempotent writes.
---

# CRM — durable memory

**Run `crm` commands with your TERMINAL tool** (on PATH; JSON output). The database is the single
source of truth — read status with `crm`, never invent it.

## When (always via terminal)
- After research: `crm log --domain D --name "Name" --sector S --source <source>`.
- Auto-measure: `enrich <domain>` (deterministic site measurement -> score in CRM).
- After contact: `crm status --domain D --to contacted -k <key>` and `crm note --domain D --body "what" -k <key>`.
- Follow-up: `crm due` / `crm hot` / `crm list --status contacted` / `crm get --domain D`.

## Commands
```
crm log    --domain D --name N [--email E] [--phone P] [--sector S] [--source SRC]
crm status --domain D --to <new|qualified|contacted|replied|meeting|won|lost|nurture> [--note T] -k KEY
crm note   --domain D --body "T" [--channel email|phone|chat] -k KEY
crm action --domain D --next "what" [--due YYYY-MM-DD]
crm get D | list [--status S] | hot | brief | health
enrich <domain>
```

## Rules
- Always pass `-k <key>` on status/note (idempotent -> no duplicates on re-run).
- Domain without www/https. A status not in the DB = "I don't know", don't guess.
- Never write the DB directly with sqlite3 — only via `crm`.
