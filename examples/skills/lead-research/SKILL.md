---
name: lead-research
description: >
  Find a SMALL number of genuinely good leads in a target market and deliver, per lead, a
  MEASURED weakness + a concrete approach. Use for "find leads", "prospects", "who can I
  reach out to", or "qualify <business>". Quality over bulk. (Example application of the system.)
---

# Lead research — quality over bulk

Goal: 2-4 HIGH-confidence leads, each with a hard, measured weakness + a ready-to-use approach.
Better 3 sharp than 30 weak. No generic list, no bulk scrape.

## Ack first
Reply `ok, doing this` + a 2-4 bullet plan. Then execute.

## GOOD vs BAD lead
GOOD (all 4): real revenue (a running business, not a hobby/non-profit with no budget); a fixable web problem (slow, no HTTPS, broken cert, not mobile-friendly, dated, or no site); a reachable decision-maker (owner, name + channel findable); an observable intent/budget signal (active on social, recent job posting, recent renovation or new service on the site).
BAD (any 1 = skip): dead / no activity; no contact channel; large chain/franchise (HQ decides); site already excellent (fast, modern, HTTPS); platform-locked site the owner tinkers with themselves.

## Per-lead playbook (research ~6, keep the top 2-4)
1. **Locate** — web search "<sector> <place>"; pick real businesses with a site.
2. **MEASURE the weakness** (hard evidence, not gut feel):
   - `whatweb -q <url>` -> platform/CMS, outdated stack.
   - `curl -sI <url>` -> HTTPS redirect, HSTS, server headers.
   - `curl -so /dev/null -w '%{time_total}\n' <url>` -> load time.
   - `echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null | openssl x509 -noout -enddate` -> cert expiry.
   - PageSpeed (if a PSI API key is configured): PSI API + `jq`. NOT local lighthouse (pulls in Chromium). `testssl <url>` only if TLS looks suspect, sparingly (slow).
   - Take the ONE sharpest number as the hook ("mobile PSI 38/100" or "load time 6.2s").
3. **Decision-maker + channel** — web search the owner; pick a direct channel (email > form > DM).
4. **Approach** — hook (the number) + angle (what it costs them: visitors bounce / search engines penalize slow sites) + a 3-4 sentence opener, direct, no flattery, low-friction ask. Apply your own pricing rule (e.g. never fully free — a no-obligation analysis or a founding deal).

## Output per lead (short)
```
[Business name] - <url>
Measured: <1 hard number/fact>
Why good: <revenue + reachability in 1 line>
Decision-maker: <name> via <channel>
Opener: "<3-4 sentences>"
```
Below it, 1 line: "want me to draft an email/DM?" — **do not send without OK.**

## Rules
- Measure ~6 sites max per run (respect rate limits). No hammering.
- `command -v <tool>` first; if whatweb/testssl/psi is missing -> say so, fall back to curl+openssl.
- Confirm before every outward action.
