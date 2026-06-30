# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

The initial set of shipped capabilities for "Your free, private, 24/7 intern" — a stdlib-only
(plus `pyyaml`) self-hosted agent runtime.

### Added

- **Model-agnostic LLM client** (`agent/llm.py`) — pick your brain via config + `.env`, no code
  change. Supports any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter, Mistral, Gemini's
  compatible endpoint, a local Ollama server), the native Anthropic Messages API, and shelling
  out to the `claude -p` CLI for a Claude subscription. A fallback chain keeps the agent alive
  when the primary provider's quota runs out.
- **Gated tool-loop** (`agent/loop.py`) — ReAct-style loop with human-in-the-loop gates enforced
  in code, not left to the model: `autonomous` (run freely), `ask_first` (require operator
  approval), `never` (always refused). A `max_steps` cap prevents runaway loops.
- **Built-in tools** (`agent/tools.py`) — `web_fetch` and `read_file` (autonomous);
  `write_file` and `run_shell` (ask_first).
- **`verify_website` tool** (`agent/tools_web.py`) — an example domain tool that measures a site
  (reachability, redirects, timing) instead of guessing.
- **Email tool** (`agent/tools_email.py`) — `email_list_recent` and `email_read` (autonomous),
  `email_send` (ask_first; prepared and approved, never auto-sent).
- **Persistent memory** (`agent/memory.py`) — local `remember` / `recall` tools so the agent
  keeps context across sessions on the box.
- **Daily-brief digest** (`agent/digest.py`) — a pre-computed daily digest delivered to the
  operator, instead of a live multi-call turn.
- **Weekly reflection** (`agent/reflect.py`) — a fail-closed weekly reflection job.
- **Usage log + daily spend cap** (`agent/usage.py`) — logs calls/cost, exposes a `usage_summary`
  tool, and refuses further API calls once the daily call or USD cap is reached.
- **Telegram gateway** (`agent/telegram.py`) — a headless 24/7 chat channel (allowlisted users)
  with inline approve/deny buttons for `ask_first` actions, so you drive the agent from your phone.
- **CLI** (`agent/cli.py`) — `python -m agent [setup|selftest|chat|telegram|digest|reflect|usage]`,
  auto-loading `.env` at startup.
- **Debian installer + setup wizard** (`install.sh`, `agent/setup.py`) — apt-installs Python if
  missing, builds the venv, seeds config; the wizard picks a brain and writes the key to `.env`
  (chmod 600) only.
- **systemd templates + docs** (`systemd/`, `docs/SETUP.md`) — fresh-Debian-to-always-on
  walkthrough with a hardened, non-sudo service unit.
- **SECURITY.md** — honest threat model: the OS (non-sudo user + systemd hardening) is the real
  safety net, prompt injection is mitigated not solved, the never-list, and the two-sided spend cap.
- **Test suite** — stdlib `unittest` tests covering the agent loop, gates, email, memory, usage,
  and reflection (no network, no credentials).

### Security

- **`run_shell` ships disabled** (`agent/tools.py`, `agent/cli.py`) — the shell tool is opt-in via
  `tools.run_shell.enabled: true`; by default the agent has no command-execution tool. When
  enabled it runs an **argv list (no `shell=True`)**, so shell metacharacters can't chain a second
  command past the approved one (keeps the child-env secret scrub). Strict opt-in parsing so a
  quoted `'false'` can't silently enable it.
- **`write_file` is jailed to the working directory** (`agent/tools.py`) — paths that resolve
  (via `realpath`, so `..`/symlinks can't escape) outside the agent's working dir are refused.

  (The SSRF egress guard, `read_file` secret-denylist, fail-closed gates, and Telegram
  refuse-to-start-on-empty-allow-list landed in the preceding hardening pass; this change builds
  on top of them.)

### Changed

- **`install.sh` renders machine-specific systemd units** into `systemd/generated/` with the real
  `User=`/paths filled in — no more copying units that contain literal `youruser` placeholders.
  The committed `systemd/*.service` files remain the editable templates.
- **`docs/SETUP.md`** points at the generated units and fixes the example `ExecStart` to run the
  headless Telegram gateway (`-m agent telegram`) instead of the interactive `chat` (which has no
  stdin under systemd and would restart-loop).
- **`.env.example`** rewritten to match the keys the code actually reads (dropped stale
  `~/.hermes` paths and unused vars).

[Unreleased]: https://github.com/lukashouthoofd/free-private-247-intern
