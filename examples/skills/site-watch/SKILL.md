---
name: site-watch
description: >
  Watch a prospect or competitor site and report ONLY when something changes (redesign, new
  service, price, job posting, dead site). Use for "keep an eye on X", "watch <url>", or via the
  weekly cron. A timing signal for warm outreach. (Example application of the system.)
---

# Site-watch

Goal: give the operator a timing hook. A prospect refreshes its site / adds a service = a moment to reach out.

## Add a site
Write to `~/.hermes/notes/watch/<slug>.json`:
`{ "url": "...", "label": "a prospect", "last_hash": "", "last_check": "" }`

## Per check (frugal — 1 fetch per site)
1. `curl -sL <url>` or `lynx -dump <url>` -> visible text.
2. Hash the core text (titles, services, prices — not dates/cookies).
3. Compare with `last_hash`:
   - No change -> report nothing, update `last_check`.
   - Change -> summarize WHAT changed, store the new hash.
   - Dead (timeout/4xx/5xx) -> report it, may be a lead itself.
4. Measure while you're there: HTTPS redirect, cert expiry (`openssl ... x509 -noout -enddate`), load time (`curl -w '%{time_total}'`).

## Report (only on change)
Short: "[label] changed: <1-2 lines what>. Outreach opportunity? <yes/no + why>." No change = stay quiet.

## Rules
- Max ~10 sites in the watchlist (budget + relevance).
- Read-only. Never fill a form or log in on a prospect's site.
