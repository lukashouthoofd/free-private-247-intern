---
name: delegate
description: >
  Decide WHEN to delegate heavy work to a top-tier coding agent (capable, expensive) vs handle it
  yourself with the cheap models. Use for real programming, complex multi-step tasks, or large
  deliverables. Protects the metered budget.
---

# When to delegate to the coding agent

Two tiers. The coding agent is capable but expensive — use it only where needed.

## Do it yourself (cheap models, default)
- Short questions, chat, explanations, summaries.
- CRM ops (`crm log/status/brief`), research, `enrich`, site measurements.
- Copy/message drafts, short web research.
- Anything your terminal tools + skills can do.

## Delegate (heavy)
- Real programming: build a feature, fix a bug, refactor in a repo.
- Complex multi-file tasks, code review, security analysis.
- Something needing deep reasoning or 10+ steps where you get stuck.

## How (via terminal)
```
claude-capped -p "<self-contained task, because the coding agent has no memory of your context>" \
  --allowedTools "Read,Edit,Bash(git *),Bash(npm *)" --max-turns 12 --output-format json
```
- Parse JSON: `.result`, `.total_cost_usd`, `.num_turns`.
- `claude-capped` enforces a daily limit that protects the budget. If refused -> say so, do it yourself with a cheaper model.

## Rule
Unsure if it's "heavy"? Try it yourself FIRST. Delegate only for real code work or when you're stuck.
