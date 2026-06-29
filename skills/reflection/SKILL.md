---
name: reflection
description: >
  Weekly self-reflection: improve from your own work. Distill durable lessons ONLY from real signal
  (a mistake the operator corrected, a repeated task pattern, a tool that failed/worked) and store
  them in memory. Never invent a lesson. Runs via the weekly cron or on "reflect".
---

# Weekly reflection — fail-closed self-learning

Goal: get a little better each week, without ever remembering something false.

## Steps
1. `hermes insights --days 7` -> which tools/skills you used, where errors/retries/token spikes were.
   (`hermes insights` is provided by the Hermes runtime, not this repo. If it's unavailable or the
   subcommand differs, degrade gracefully: review recent CRM notes and the last few transcripts by hand.)
2. Review recent work for REAL signals:
   - A mistake the operator corrected ("no, do X instead of Y").
   - A task pattern that repeated 2+ times.
   - A tool/skill that failed or worked notably well — and why.
3. Per REAL signal -> one concise, concrete lesson (no platitudes like "be careful").

## HARD rule (fail-closed — non-negotiable)
- No real signal found -> write NOTHING. Just say "no new lessons this week".
- NEVER invent a lesson, mistake, or pattern that wasn't there. Better to learn nothing than learn something wrong.
- Unsure it's a real signal? -> don't store it.

## Store
- Confirmed lessons -> memory, phrased short and reusable.
- A workflow that repeated 3+ times identically -> propose turning it into a skill via `/learn`.

## Report (chat, short)
"Reflection: <N lessons> — <one line each>" or "Reflection: no new lessons this week."
