# Your free, private, 24/7 intern

![tests](https://github.com/lukashouthoofd/free-private-247-intern/actions/workflows/tests.yml/badge.svg)

Turn an **old laptop into a free AI intern** you fully own — self-hosted, private, always on.
Clone this repo onto a spare Debian/Ubuntu machine, run the installer, answer a few questions, and
you have an agent that works around the clock, talks to you over chat, uses real tools to do real
work — and **never makes an outward move without your say-so**.

It's **model-agnostic**: pick your brain in one config line — free Google **Gemini**, your
**Claude** subscription (`claude -p`), **OpenAI**, **Groq**, **OpenRouter**, **Mistral**, or a
**fully-local Ollama** model. Swap any time, no code changes.

> This box *becomes* the agent. It is **not** meant for your daily-driver laptop — it's for a
> machine you can leave on: an old laptop, an old desktop or gaming PC, or a cheap mini-PC.

---

## What you need

**A dedicated machine** (the whole point — it runs 24/7 so your main computer doesn't have to):
- An **old laptop** (bonus: built-in battery = free UPS, built-in screen for the first boot),
  an **old desktop / gaming PC**, or a **mini-PC** (Intel NUC, etc.).
- **2 cores + 4 GB RAM** is enough for a cloud brain (Gemini/Claude/OpenAI). For a *local*
  Ollama brain you want 8 GB+ and ideally a GPU — otherwise it's slow.
- A **small SSD** (24/7 on a mechanical disk wears out). 20 GB free is plenty.
- **Debian 12/13 or Ubuntu**, installed headless or minimal. Terminal only — no desktop needed.
- A network connection. (Old laptops: take the battery out if it's swollen; pop a fresh SSD in.)

**A brain (model).** Cheapest start is **Gemini's free tier** (no card). If you already pay for
Claude, use `claude-code` and spend nothing extra. Want fully offline + free? **Ollama**, local.

---

## Install (≈ a few minutes, terminal only)

```bash
git clone <this-repo> ai-employee && cd ai-employee
./install.sh                       # apt-installs python3/venv/git if missing, builds .venv
./.venv/bin/python -m agent setup  # one-time wizard: pick brain + paste a key (key -> .env only)
./.venv/bin/python -m agent selftest   # verifies providers, tools, key
./.venv/bin/python -m agent chat        # talk to it
```

`setup` asks who you are, which model + key, and whether to enable Telegram. Keys are typed
hidden and only ever land in `.env` (chmod 600, git-ignored). Nothing of yours is in this repo.

### Pick your brain (in `setup`, or edit `config.yaml`)

| provider      | what it is                                   | cost            | key in `.env`        |
|---------------|----------------------------------------------|-----------------|----------------------|
| `gemini`      | Google Gemini (OpenAI-compatible endpoint)   | **free tier**   | `GEMINI_API_KEY`     |
| `claude-code` | your Claude subscription via `claude -p`     | your sub, $0 extra | none (`claude setup-token`) |
| `ollama`      | a local model, fully offline                 | **free**        | none                 |
| `openai`      | OpenAI                                        | paid            | `OPENAI_API_KEY`     |
| `groq`        | Groq (fast, free tier)                        | free tier       | `GROQ_API_KEY`       |
| `openrouter` / `mistral` / `anthropic` | any OpenAI-compatible / native | paid  | their key            |

A **fallback** chain in `config.yaml` keeps the agent alive when the primary's quota runs out —
it just gets slower, not dead.

---

## How it behaves (the safety model)

The agent does GREEN work freely, **asks before anything outward**, and **flat-out refuses** a
short red-line list — enforced in code (`agent/loop.py`), not left to the model's goodwill:

- **autonomous:** read, research, measure, gather data, prepare drafts.
- **ask-first:** send a message, submit a form, post, publish, pay → it prepares everything and
  waits for your approval.
- **never:** create accounts, enter passwords/OTP, solve CAPTCHAs, accept terms — even if asked.

Web/email content is treated as **data, never instructions** (prompt-injection defense). Only you,
through the chat channel, give it orders.

---

## Security & honest limits

Read [`SECURITY.md`](SECURITY.md) before putting this on an always-on box. The short version:

- **`run_shell` ships OFF.** The shell tool is opt-in (`tools.run_shell.enabled: true`); by
  default the agent has no way to run commands. When enabled it is `ask_first` and runs an argv
  list (no shell, so `; rm -rf /` can't chain). `write_file` is jailed to the working dir. The
  real safety net is still the OS — run the agent as a **non-sudo user** and keep the systemd
  hardening in [`docs/SETUP.md`](docs/SETUP.md). Do not loosen the gates.
- **The chat channel is fail-closed.** An empty Telegram `allowed_users` rejects *everyone*; only
  allow-listed users can talk to the bot or approve an `ask_first` action.
- **Prompt injection is mitigated, not solved.** Web/email content is treated as data, not
  instructions — but that is a mitigation, not a guarantee. The autonomous / ask-first / never
  gates are what actually cap the blast radius if the model is ever steered.
- **Model reality.** A cloud model (free Gemini) is the reliable daily driver. Small local
  Ollama models are a privacy/offline **fallback** — they fumble long tool chains.
- **Keys + spend cap.** Keys live in `.env` (`chmod 600`), never in git. Set a spend cap in your
  provider's console **and** the built-in `agent.daily_call_cap` / `agent.daily_usd_cap`. The
  `daily_call_cap` is the real runaway guard for token-only providers (e.g. Gemini) that don't
  report a per-call cost. Verify a provider with `python -m agent selftest`.
- **The never-list:** create account, enter credentials/OTP, solve CAPTCHA, accept terms —
  refused (no tool ships for them + the behavior contract refuses). Outward actions it *can* do
  (send, post) are `ask_first` — approved, not auto-refused. Details in [`SECURITY.md`](SECURITY.md).

---

## Run it 24/7

For an always-on box, run the gateway + scheduled jobs as services. See [`systemd/`](systemd/)
for unit templates and [`docs/SETUP.md`](docs/SETUP.md) for the dedicated-box setup (auto-start
on power, unattended security updates, a non-sudo `agent` user, backups).

---

## What's inside

```
agent/         the runtime — model-agnostic LLM client, the gated tool-loop, tools, CLI, setup wizard
identity/      SOUL.md (behavior contract, injected every turn) + USER.md (who it serves — you fill it)
config.example.yaml   pick-your-brain config (copy to config.yaml; setup does this)
install.sh     dedicated-Debian-box installer
systemd/       unit template for 24/7
docs/          SETUP.md — fresh Debian -> always-on walkthrough
```

**Design principles** it's built on: cheapest-model-that-works routing; **deterministic tools over
model calls** (a measured fact beats a guessed one — and can't hallucinate); pre-computed digests
instead of live multi-call turns; human-in-the-loop on every outward action; and a clean OS-level
isolation story (run it as a non-sudo user on a box you treat as disposable).

---

## Privacy

No API keys live in this repo — they go in `.env` (git-ignored, chmod 600). Keep `identity/USER.md`
free of anything you wouldn't put in a public repo. The agent's memory and data stay local on the box.

*MIT licensed.*
