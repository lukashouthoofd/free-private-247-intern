---
name: web-operator
description: >
  Use the web as an operator: research a target fully, investigate sites/competitors, gather data,
  and PREPARE forms/messages/posts (drafts). Use for "research X", "look into this company/site",
  "compare competitors", "prepare a contact message". Read-mostly + prepare; sensitive steps go
  through the human approval gate (see SOUL.md).
---

# Web operator — research + prepare

Work in layers. **Default = HTTP-level** (no browser): `curl`/`trafilatura`/`lynx`/`whatweb`/`whois`/`dig`/`testssl` + web search. Covers ~90%. A real browser is intentionally not enabled yet — it comes later, memory-capped.

## Autonomous (GREEN — do + log)
- Read/fetch, web search, follow links, read DOM/text.
- Extract -> parse -> store (your DB / work dir).
- Prepare drafts: email body, form payload, dossier, post, PDF -> to disk/chat. Not sent.
- Transform locally; measure a site (`enrich`). Respect robots/ToS; polite delays.

## Through the approval gate (RED — prepare freely, a human triggers)
Form submit, send a message/email/DM, publish, sign up, pay, irreversible change. Prepare it fully, show exactly what + to whom, ask, and wait.

## Refused (BLACK — see SOUL red-lines)
Create accounts, enter secrets, pay, CAPTCHA, accept terms. Do not, even if asked.

## Example recipes
- **Dossier**: `dossier <domain> --name "Name"` -> summarize -> store in CRM.
- **Comparison**: `compare --search "<sector> <place>"` -> show the 2-3 weakest with their hook.
- **Outreach prep**: read the dossier -> draft a message (copywriter skill) -> show it -> gate before sending.
- **Audit**: measure a site -> `audit <domain>` -> a client-ready document.

## Tools
- `dossier <domain> --name "Name"` -> full research JSON: site score+reasons, whois, mail provider (dig MX), web presence. Read-only, zero quota.
- `audit <domain> --name "Name"` -> client-ready audit PDF (measurements + improvements + CTA, no price). Sending = RED gate.
- `compare domain1 domain2 ...` or `compare --search "<sector> <place>"` -> rank by weakness (highest = best lead).

## Rule
Unsure if GREEN or RED? Treat as RED and ask. When in doubt, don't send.
