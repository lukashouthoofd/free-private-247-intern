#!/usr/bin/env bash
# ============================================================================
#  Your free, private, 24/7 intern — installer for a DEDICATED Debian/Ubuntu machine.
#  This box BECOMES the agent (an old laptop / mini-PC / old desktop or gaming
#  PC) — NOT your daily driver. Terminal only, no GUI needed.
#
#  Usage (from the repo root):   ./install.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m>> %s\033[0m\n' "$*"; }

# 1. System packages (Debian/Ubuntu). Auto-installs Python if it isn't there.
if command -v apt-get >/dev/null 2>&1; then
  missing=()
  for pkg in python3 python3-venv python3-pip git; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    say "Installing system packages: ${missing[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y "${missing[@]}"
  else
    say "System packages already present (python3, venv, pip, git)"
  fi
else
  echo "!! This installer targets Debian/Ubuntu (apt). On another distro install" >&2
  echo "   python3 + python3-venv + git yourself, then re-run." >&2
fi

command -v python3 >/dev/null 2>&1 || { echo "python3 is still missing — aborting." >&2; exit 1; }
say "Python: $(python3 --version)"

# 2. Virtualenv + Python deps (tiny: only PyYAML; the rest is stdlib).
say "Creating .venv and installing requirements"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

# 3. Seed config + secrets from templates (NEVER overwrite an existing one).
[ -f config.yaml ] || { cp config.example.yaml config.yaml; echo "  seeded config.yaml"; }
if [ ! -f .env ]; then
  cp .env.example .env 2>/dev/null || touch .env
  chmod 600 .env
  echo "  seeded .env (chmod 600) — your API keys live here, never in git"
fi
mkdir -p data/memory

# 4. Generate systemd units for THIS machine (fill in the real user + paths — no manual editing).
say "Writing systemd units for this machine into systemd/generated/"
REPO_DIR="$(pwd)"
RUN_USER="$(id -un)"
mkdir -p systemd/generated
for unit in ai-employee.service ai-employee-digest.service ai-employee-reflect.service; do
  sed -e "s#/home/youruser/ai-employee#${REPO_DIR}#g" \
      -e "s#^User=youruser#User=${RUN_USER}#" \
      "systemd/${unit}" > "systemd/generated/${unit}"
done
cp systemd/ai-employee-digest.timer systemd/ai-employee-reflect.timer systemd/generated/ 2>/dev/null || true
echo "  units use  User=${RUN_USER}  WorkingDirectory=${REPO_DIR}  (ready to copy, no edits needed)"

# 5. Done — next steps.
say "Installed. Next:"
cat <<EOF
  ./.venv/bin/python -m agent setup      # one-time wizard: pick your brain + paste a key
  ./.venv/bin/python -m agent selftest   # verify providers/tools/key
  ./.venv/bin/python -m agent chat        # talk to it

  Brains you can pick (in setup): gemini (free) · claude-code (your Claude subscription)
  · openai · groq · openrouter · mistral · ollama (fully local) · anthropic

  For 24/7 unattended operation (dedicated box) — units were generated for you:
    sudo cp systemd/generated/*.service systemd/generated/*.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now ai-employee                                   # the Telegram gateway
    sudo systemctl enable --now ai-employee-digest.timer ai-employee-reflect.timer
    journalctl -u ai-employee -f
  (full walkthrough: docs/SETUP.md)
EOF
