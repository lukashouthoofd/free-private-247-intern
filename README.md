# Self-Hosted AI Employee

A reference architecture for turning an open-source agent runtime into a reliable **24/7 "digital employee"** on a small, cheap home server (8 GB RAM, no GPU).

This repo is about the **system** — the patterns that make a free/cheap LLM behave like a dependable autonomous worker — not about any single application. The example tools (CRM, site research, document generation) are just there to *demonstrate* the patterns; swap them for your own.

It runs on top of [Hermes Agent](https://hermes-agent.nousresearch.com/) (the agent runtime + Telegram gateway), but the ideas are runtime-agnostic.

> ⚠️ **No secrets in this repo.** All API keys live in `~/.hermes/.env` (chmod 600, never committed) — see [`.env.example`](.env.example). User data (`*.db`) stays local.

---

## The system — six patterns

The whole design exists to solve one problem: *make an agent that's cheap to run, hard to break, and honest.*

### 1. Cost-tiered model routing
Route every task to the **cheapest model that can actually do it**, and escalate only when needed.

| Work | Model tier | Why |
|------|-----------|-----|
| Main agentic turn (tools, large context) | a capable cloud model (free or paid) | only tier that drives a multi-tool turn reliably |
| Voice → text | a fast speech API | audio doesn't count against text rate limits |
| Tiny / high-frequency / offline fallback | a small **local** model | free, no rate limit, works offline |
| Heavy reasoning / real coding | a top-tier model behind a daily cap | capable; capped to protect the budget |

A fallback chain (`primary → cheaper cloud → local`) means the agent stays *alive* even when the primary's quota is gone — it just gets slower, not dead.

### 2. Deterministic tools over model calls
Wrap real work — measuring, fetching, transforming, document generation — in **plain CLI tools** that cost **zero model quota** and **cannot hallucinate**. The model orchestrates; the tools do the work and return JSON. A measured fact beats a guessed one, and it's free.

### 3. The digest pattern (the biggest quota saver)
A deterministic pipeline pre-computes a **JSON digest** on a schedule. The agent then *reads the digest* instead of gathering data live through expensive multi-call turns. One cron run replaces dozens of model turns.

### 4. Read-mostly + human-in-the-loop gates
The agent **prepares everything; a human pulls every outward or irreversible trigger.**

- 🟢 **GREEN (autonomous):** read, research, gather data, prepare drafts (emails, documents, payloads).
- 🔴 **RED (approval via chat):** submit a form, send a message, publish, sign up → fully prepared, *you* press the button.
- ⚫ **BLACK (always refused):** create accounts, enter credentials/OTP, pay, solve CAPTCHAs, accept terms — even if asked.

Web/document content is treated as **data, never instructions** (prompt-injection defense). Only the operator, via the chat channel, gives commands.

### 5. Fail-closed self-learning
A periodic reflection distills durable lessons **only from real signal** (a corrected mistake, a repeated pattern, a tool that failed) and **never invents** one. No signal → no lesson. A weak model that hallucinates "learnings" is worse than one that learns nothing.

### 6. OS-level isolation & hardening
The agent runs as an **isolated non-sudo user**; the service is **systemd-hardened** (`ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `MemoryMax`). The agent has **no long-lived browser yet** — on an 8 GB box that would risk OOM — but when one is added it runs in a **memory-capped cgroup slice** so a heavy task can't take down the host. The permission layer is a convenience; OS isolation is the real safety net.

---

## How it fits together

```
  operator ──(chat)──▶  agent turn  ──┬──▶  deterministic tools (bin/*, zero quota) ──▶ JSON
                                      │
   cost-tiered routing:               └──▶  human gate:  GREEN do · RED ask · BLACK refuse
   claude-capped ▶ Groq ▶ Gemini ▶ Ollama          (every outward / irreversible action)

  cron ──▶ pipeline.py ──▶ brief.json  ───▶  daily-brief reads the digest, not live data
                       (the digest pattern: one cron run replaces dozens of model turns)
```

## Components

```
identity/   SOUL.md  — the agent's behavior contract (ack→plan→execute, the gates, the red-lines)
            USER.md  — who the agent serves (template)
bin/        deterministic CLI tools (zero model quota) — see below
skills/     core system skills (the patterns above, as agent instructions)
examples/   application skills + their domain logic (swap for your own use case)
config/     config.example.yaml (model tiering, fallback chain)
systemd/    service + timer units (gateway, scheduled pipeline)
scripts/    install.sh (idempotent setup)
.env.example, .gitignore, LICENSE
```

### Example tools (`bin/`) — demonstrate pattern #2
| Tool | What it shows |
|------|---------------|
| `crm` | a SQLite system-of-record with **idempotent** writes (re-runnable, no duplicates) |
| `enrich` | measure a website deterministically → a 0-100 score + reasons (no guessing) |
| `dossier` | combine several read-only sources into one structured record |
| `audit` | turn a measurement into a client-ready PDF (deterministic → document) |
| `compare` | rank multiple inputs by a measured signal |
| `pipeline` | the **digest pattern**: scheduled, deterministic, writes a JSON the agent reads |
| `claude-capped` | a daily-capped wrapper around a metered CLI (budget protection) |

All print JSON and run in a dedicated Python venv.

---

## Example application

The included example wires the system into a **lead-research assistant**: find a business, measure its website, build a dossier, store it, and prepare outreach — fully autonomous up to the gate, where a human approves anything that goes out. It's one application of the system; the architecture is the point.

---

## Deployment

Two manual prerequisites — they need root and are environment-specific:

1. **Create a dedicated, non-sudo service user.** The tools and units assume a user named `hermes` with home `/home/hermes`, so its config dir is `~/.hermes` (the bin wrappers hardcode this path).
2. **Install the [Hermes Agent](https://hermes-agent.nousresearch.com/) runtime + a small local model** — e.g. `ollama pull qwen2.5:3b` (matches the config fallback chain).

Then, **as the `hermes` user**, the rest is one idempotent command:

```bash
scripts/install.sh
```

It lays out `~/.hermes/`, creates the tools venv + installs deps, seeds `~/.hermes/.env` (chmod 600) and `config.yaml` from the templates, and symlinks the tool wrappers (`crm`, `enrich`, `dossier`, `audit`, `compare`, `pipeline`, `claude-capped`) onto `PATH`. Both `skills/` (core) and `examples/skills/` (applications) are copied into `~/.hermes/skills/` — the repo splits them only for readability. The script finishes by printing the remaining **root** steps:

- System CLIs the example tools call: `sudo apt install whatweb testssl.sh lynx pandoc weasyprint poppler-utils sqlite3 dnsutils whois jq`
- Install the units from `systemd/` and `systemctl enable --now hermes-gateway hermes-pipeline.timer hermes-pipeline-weekly.timer`.

Finally, fill in your real keys in `~/.hermes/.env` and set your model tiers in `~/.hermes/config.yaml`. Verify with `crm health`.

---

## Honest limitations

- **Free LLM tiers are weak or rate-limited.** On a free/fallback model the agent often isn't smart enough for reliable autonomous multi-tool reasoning. A dependable daily driver needs a paid main model (or a subscription-based CLI for the heavy work). The deterministic tools, however, always work — that's the point of pattern #2.
- **8 GB / no GPU:** no large local models, no long-lived headless browser (OOM risk). Real GUI/desktop control belongs on a machine with a display.

---

*Licensed MIT — see [LICENSE](LICENSE). Built on [Hermes Agent](https://hermes-agent.nousresearch.com/) (© Nous Research, MIT), a separate project; this repo is a configuration/architecture layer on top of it.*
