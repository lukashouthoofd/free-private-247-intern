# Dedicated-box setup — fresh Debian → 24/7 intern

This is the full walkthrough for turning a spare machine into an always-on agent. Budget ~1–2
hours. You only need a screen + keyboard for the first 10 minutes; after that it's SSH-only.

## 0. Hardware prep (old machines)
- **Swap in an SSD** if it still has a spinning disk — 24/7 writes kill old HDDs, and an SSD is
  the single best reliability upgrade (~€25).
- **Old laptop?** Remove a swollen battery (fire risk on 24/7); a healthy battery is a free UPS.
- **Dust it out**, make sure it isn't in a closed drawer (heat = shutdowns).
- In the **BIOS**: set *Restore on AC Power Loss = Power On* (auto-start after an outage), and
  enable *Wake-on-LAN* if you want to power it remotely.

## 1. Install Debian (headless)
- Flash Debian 12/13 "netinst" to a USB stick, boot it, choose a **minimal install**: tick only
  *SSH server* + *standard system utilities*. **No desktop.**
- Make a normal user (not root). After reboot, find its IP (`ip a`) and from your main machine:
  `ssh youruser@<ip>`. You won't need the screen again.
- Harden SSH (`/etc/ssh/sshd_config`): `PermitRootLogin no`, `PasswordAuthentication no` (after
  you've added your key with `ssh-copy-id`), then `sudo systemctl restart ssh`.

## 2. Auto-patching (unattended box)
```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # security updates only
```

## 3. Install the agent
```bash
git clone <this-repo> ai-employee && cd ai-employee
./install.sh
./.venv/bin/python -m agent setup       # pick brain + key
./.venv/bin/python -m agent selftest
```
If you chose `claude-code`, run `claude setup-token` once. If you chose `ollama`,
`ollama pull <model>` first.

## 4. Run it 24/7 (systemd)
Run the agent under its own user, auto-restarting, surviving reboots. Create
`/etc/systemd/system/ai-employee.service` (adjust `User=` and the path):

```ini
[Unit]
Description=Your free, private, 24/7 intern
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/ai-employee
ExecStart=/home/youruser/ai-employee/.venv/bin/python -m agent chat
Restart=on-failure
RestartSec=10
# hardening: the agent is treated as untrusted
MemoryMax=2G
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/youruser/ai-employee

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ai-employee
journalctl -u ai-employee -f          # watch it
```
> The CLI `chat` is interactive; for a true headless gateway use the Telegram channel
> (`channels.telegram.enabled: true` + `TELEGRAM_BOT_TOKEN` in `.env`) so you talk to it from
> your phone. Scheduled jobs (daily digest, weekly reflection) go in their own systemd `*.timer`
> units — see `config.yaml` `schedule:`.

## 5. Safety on an unattended box
- Run the agent as a **non-sudo user** — that's the layer that holds if the model is ever tricked.
- Keep `.env` `chmod 600`. Set a **spend cap** in your model provider's console as a financial
  dead-man's-switch (especially for paid APIs).
- The agent already refuses account-creation / credentials / CAPTCHAs / payments in code; don't
  loosen those gates.

## 6. Backups
Nightly, push your `data/` (memory, any SQLite) somewhere off-box (a `git push` to a private repo,
or `rsync` to your main machine). A dead SSD then means: new SSD, reinstall, `git pull`, run.

## Troubleshooting
- `python -m agent selftest` says **KEY MISSING** → put the key in `.env`, or re-run `setup`.
- Model calls fail → check the provider/model id in `config.yaml` and that the key is valid.
- Out of quota → add a `fallback:` entry (e.g. local `ollama`) in `config.yaml`.
