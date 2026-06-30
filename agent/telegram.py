"""
Telegram gateway — talk to your agent from your phone, headless, 24/7.

Long-polls Telegram (stdlib only), runs each message from an ALLOWED user through the agent
loop, and streams the reply back. The human-in-the-loop gate works over chat: when the agent
wants to do an `ask_first` action it messages you "Approve 'send_mail'? reply yes/no" and waits
for your reply before proceeding. Unknown users are ignored.

Set it up:  channels.telegram.enabled: true + allowed_users: [<your numeric id>]  in config.yaml,
            TELEGRAM_BOT_TOKEN=...  in .env. Get a token from @BotFather; get your id from @userinfobot.
Run:        python -m agent telegram
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Callable

API = "https://api.telegram.org/bot{token}/{method}"
_OK = {"yes", "y", "ok", "oke", "oké", "ja", "do it", "go", "approve", "👍"}


class TelegramGateway:
    def __init__(self, token: str, allowed_users, agent_factory: Callable, logger=print):
        self.token = token
        self.allowed = {int(u) for u in (allowed_users or [])}
        self.agent_factory = agent_factory          # (approver) -> Agent
        self.logger = logger
        self.offset = 0

    def _api(self, method: str, **params) -> dict:
        url = API.format(token=self.token, method=method)
        data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(url, data=data)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            self.logger(f"telegram api error ({method}): {e}")
            return {"ok": False}

    def send(self, chat_id: int, text: str) -> None:
        for i in range(0, max(1, len(text)), 4000):       # Telegram caps messages at 4096 chars
            self._api("sendMessage", chat_id=chat_id, text=text[i:i + 4000])

    def _pull(self, timeout: int = 25) -> list[dict]:
        """Return new message updates and advance the offset."""
        data = self._api("getUpdates", offset=self.offset, timeout=timeout)
        msgs = []
        for upd in data.get("result", []):
            self.offset = upd["update_id"] + 1
            m = upd.get("message") or {}
            if m.get("text"):
                msgs.append({"uid": (m.get("from") or {}).get("id"),
                             "chat_id": (m.get("chat") or {}).get("id"),
                             "text": m["text"]})
        return msgs

    def _wait_reply(self, chat_id: int, timeout_s: int = 300) -> str:
        """Block until the operator sends the next message in this chat (for approvals)."""
        elapsed = 0
        while elapsed < timeout_s:
            for m in self._pull(timeout=20):
                if m["chat_id"] == chat_id and (not self.allowed or m["uid"] in self.allowed):
                    return m["text"]
            elapsed += 20
        return ""

    def run(self) -> None:
        me = self._api("getMe")
        if not me.get("ok"):
            raise SystemExit("Telegram: bad token (set TELEGRAM_BOT_TOKEN in .env). getMe failed.")
        self.logger(f"telegram gateway up as @{me['result'].get('username')} "
                    f"(allowed users: {sorted(self.allowed) or 'ANYONE — set allowed_users!'})")
        while True:
            for m in self._pull():
                chat_id, uid, text = m["chat_id"], m["uid"], m["text"]
                if self.allowed and uid not in self.allowed:
                    self.send(chat_id, "Sorry, you're not on this agent's allow-list.")
                    self.logger(f"ignored message from {uid}")
                    continue

                def approver(name: str, args: dict, _cid=chat_id) -> bool:
                    self.send(_cid, f"⏸ Approve '{name}'? reply *yes* or *no*\n{json.dumps(args)[:600]}")
                    return self._wait_reply(_cid).strip().lower() in _OK

                agent = self.agent_factory(approver)
                self.send(chat_id, "…working")
                try:
                    reply = agent.run(text)
                except Exception as e:
                    reply = f"error: {e}"
                self.send(chat_id, reply or "(no answer)")
