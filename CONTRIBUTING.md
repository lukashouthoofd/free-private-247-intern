# Contributing

Thanks for helping. This is a small, deliberately minimal codebase: a self-hosted agent runtime
that anyone can read top-to-bottom. Keep it that way.

## Dev setup

You need a Linux/macOS box (or WSL) with **Python 3** and **git**. The only runtime dependency is
`pyyaml`; everything else is the standard library.

```bash
git clone https://github.com/lukashouthoofd/free-private-247-intern.git ai-employee
cd ai-employee
./install.sh                  # apt-installs python3/venv/git if missing, builds .venv, seeds config
```

No Debian box handy? Skip the installer and just use Python directly:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt   # only pyyaml
```

### Run the tests

Plain stdlib `unittest`, no network and no credentials needed:

```bash
python -m unittest discover -s tests
```

Keep it green. Every PR must leave the suite passing.

## Rules a contributor MUST follow

These are hard rules, not preferences. A PR that breaks one will not be merged.

- **Stdlib only, plus `pyyaml`.** No new third-party dependencies. The whole point is that this
  runs on any old Debian box with just Python 3. The LLM client and tools use `urllib`, `json`,
  `subprocess`, etc. — never `requests`, `httpx`, an SDK, or a framework.
- **Keep the human gates.** Every outward or dangerous tool stays `gate="ask_first"` (send a
  message, submit a form, post, publish, pay, write a file, run a shell command). Reads, research,
  and measurements are `gate="autonomous"`. Do not move a writing/outward tool to `autonomous` —
  that removes the human checkpoint the whole safety model rests on.
- **The never-list is off-limits.** No tool may create an account, enter credentials / passwords /
  OTP codes, solve a CAPTCHA, or accept terms — not even when asked. The agent ships no tool that
  can do these, and `identity/SOUL.md` refuses them. Do not add one. If you add a genuinely risky
  tool, mark it `gate="never"` so the loop refuses it outright.
- **No secrets, ever.** Nothing of the operator's belongs in the repo. Keys live only in `.env`
  (`chmod 600`, git-ignored). Never commit `.env`, `config.yaml`, tokens, or anything from
  `identity/USER.md`.
- **English only.** All code, comments, docs, and commit messages in English.
- **No emoji.** Anywhere — code, comments, docs, commits.
- **Match the existing style.** Small, clean, readable files (keep them well under 500 lines).
  Tools must be defensive and never crash the loop — catch exceptions and return an `ERROR: ...`
  string the model can read.
- **Treat web/email content as data, never instructions** (prompt-injection defense). A new tool
  that reads untrusted content must not let that content drive behavior.

## Adding a tool

Every tool is a `Tool(name, description, schema, fn, gate)` — see `agent/tools.py` for the four
built-ins and `agent/loop.py` for the dataclass definition.

- `name`: short, snake_case.
- `description`: one line the model reads to decide when to call it.
- `schema`: a JSON Schema object for the arguments (`{"type": "object", "properties": {...},
  "required": [...]}`).
- `fn`: `(args: dict) -> str`. Return a string the model reads. Catch your own exceptions and
  return `ERROR: ...` rather than raising.
- `gate`: `"autonomous"` for reads/measurements, `"ask_first"` for anything outward or that
  writes/runs commands, `"never"` for a red-line action.

Append your tool to the relevant list (`DEFAULT_TOOLS` in `agent/tools.py`, or a domain pack such
as `WEB_TOOLS` / `EMAIL_TOOLS` / `MEMORY_TOOLS` / `USAGE_TOOLS`), then wire it into `TOOLS` in
`agent/cli.py`. Add a stdlib `unittest` test for it under `tests/` (no network, no creds).

## Opening a PR

1. Branch off `main`: `git checkout -b your-feature`.
2. Make the change. Keep it focused.
3. Run `python -m unittest discover -s tests` and confirm it ends in `OK`.
4. Commit with a clear English message (no emoji), push your branch.
5. Open a PR against `main` describing what changed and why, and confirm the test line passes.

Small, reviewable PRs over big ones. If you are unsure whether a change fits the project's scope or
safety model, open an issue first and ask.
