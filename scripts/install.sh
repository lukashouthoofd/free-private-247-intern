#!/usr/bin/env bash
#
# Idempotent installer for the self-hosted AI employee tools + skills.
#
# Run this AS the dedicated, non-sudo service user (default: a user named `hermes`
# whose HOME is /home/hermes, so HERMES_HOME resolves to /home/hermes/.hermes —
# the path the bin/ wrappers and systemd units hardcode). It does NOT use sudo and
# never touches anything outside $HERMES_HOME and ~/.local/bin.
#
# What it does (safe to re-run):
#   - lays out ~/.hermes (bin, skills, identity, config, data, export)
#   - creates a Python venv for the deterministic tools + installs their deps
#   - symlinks the tool wrappers onto PATH (~/.local/bin)
#   - seeds ~/.hermes/.env (chmod 600) and config.yaml from the templates if absent
#
# It does NOT (these need root / are environment-specific — see README "Deployment"):
#   - create the service user, install the Hermes runtime, apt-install system CLIs,
#     or install the systemd units. It prints those next steps at the end.

set -euo pipefail

HERMES="${HERMES_HOME:-$HOME/.hermes}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCALBIN="${LOCALBIN:-$HOME/.local/bin}"

echo ">> Installing into $HERMES  (from repo $REPO)"

# 1. Layout
mkdir -p "$HERMES"/{bin,skills,data,export/out,notes}

# 2. Code + skills + identity + config
#    skills/ (core) and examples/skills/ (applications) both land in ~/.hermes/skills/
#    so the runtime activates them; the repo keeps them split only for readability.
cp -r "$REPO"/bin/. "$HERMES"/bin/
cp -r "$REPO"/skills/. "$HERMES"/skills/
[ -d "$REPO/examples/skills" ] && cp -r "$REPO"/examples/skills/. "$HERMES"/skills/
cp "$REPO"/identity/SOUL.md "$REPO"/identity/USER.md "$HERMES"/
chmod +x "$HERMES"/bin/* 2>/dev/null || true

# 3. Secrets + config from templates (never overwrite existing)
if [ ! -f "$HERMES/.env" ]; then
  cp "$REPO/.env.example" "$HERMES/.env"
  chmod 600 "$HERMES/.env"
  echo ">> Created $HERMES/.env from template (chmod 600) — fill in your real keys."
fi
[ -f "$HERMES/config.yaml" ] || cp "$REPO/config/config.example.yaml" "$HERMES/config.yaml"

# 4. Tools venv + dependencies
if [ ! -d "$HERMES/tools-venv" ]; then
  python3 -m venv "$HERMES/tools-venv"
fi
"$HERMES/tools-venv/bin/pip" install --quiet --upgrade pip
"$HERMES/tools-venv/bin/pip" install --quiet ddgs weasyprint

# 5. PATH symlinks for the wrappers
mkdir -p "$LOCALBIN"
for t in crm enrich dossier audit compare pipeline claude-capped; do
  [ -f "$HERMES/bin/$t" ] && ln -sf "$HERMES/bin/$t" "$LOCALBIN/$t"
done

echo
echo ">> Done. Tools installed and symlinked into $LOCALBIN."
echo "   Verify: crm health   (expect JSON ok:true)"
echo
echo ">> Remaining steps that need root / your runtime (see README 'Deployment'):"
echo "   1. Install the Hermes Agent runtime + a local model (e.g. ollama pull qwen2.5:3b)."
echo "   2. System CLIs used by the example tools:"
echo "      sudo apt install whatweb testssl.sh lynx pandoc weasyprint poppler-utils sqlite3 dnsutils whois jq"
echo "   3. Install systemd units:"
echo "      sudo cp $REPO/systemd/*.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload"
echo "      sudo systemctl enable --now hermes-gateway hermes-pipeline.timer hermes-pipeline-weekly.timer"
