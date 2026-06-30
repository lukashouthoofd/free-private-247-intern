"""
Telegram gateway — talk to your agent from your phone, headless, 24/7.

Long-polls Telegram (stdlib only), runs each message from an ALLOWED user through the agent
loop, and streams the reply back. The human-in-the-loop gate works over chat: when the agent
wants to do an `ask_first` action it sends you Approve / Deny inline BUTTONS and waits for you
to press one before proceeding. Typing "yes"/"no" still works as a fallback. Unknown users are
ignored.

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
_OK = {"yes", "y", "ok", "oke", "oké", "ja", "do it", "go", "approve"}

# Inline keyboard shown for every ask_first approval (plain words, no emoji).
_APPROVE_KB = {"inline_keyboard": [[
    {"text": "Approve", "callback_data": "approve"},
    {"text": "Deny", "callback_data": "deny"},
]]}


class TelegramGateway:
    def __init__(self, token: str, allowed_users, agent_factory: Callable, logger=print):
        self.token = token
        self.allowed = {int(u) for u in (allowed_users or [])}
        self.agent_factory = agent_factory          # (approver) -> Agent
        self.logger = logger
        self.offset = 0

    def _api(self, method: str, **params) -> dict:
        url = API.format(token=self.token, method=method)
        # dict/list params (e.g. reply_markup) must be JSON-encoded for Telegram.
        flat = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                for k, v in params.items() if v is not None}
        data = urllib.parse.urlencode(flat).encode()
        req = urllib.request.Request(url, data=data)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            self.logger(f"telegram api error ({method}): {e}")
            return {"ok": False}

    def send(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        chunks = range(0, max(1, len(text)), 4000)         # Telegram caps messages at 4096 chars
        n = len(text)
        for i in chunks:
            # only attach the keyboard to the final chunk so the buttons sit under the whole text
            kb = reply_markup if i + 4000 >= n else None
            self._api("sendMessage", chat_id=chat_id, text=text[i:i + 4000], reply_markup=kb)

    def _pull(self, timeout: int = 25) -> list[dict]:
        """Return new updates (messages AND button presses) and advance the offset.

        Each item is a dict with uid/chat_id/text. Button presses also carry callback_id
        (to answer the callback) and data (the callback_data, e.g. 'approve'/'deny')."""
        data = self._api("getUpdates", offset=self.offset, timeout=timeout)
        msgs = []
        for upd in data.get("result", []):
            self.offset = upd["update_id"] + 1
            cb = upd.get("callback_query")
            if cb:                                          # operator pressed an inline button
                msg = cb.get("message") or {}
                msgs.append({"uid": (cb.get("from") or {}).get("id"),
                             "chat_id": (msg.get("chat") or {}).get("id"),
                             "text": cb.get("data") or "",
                             "callback_id": cb.get("id"),
                             "data": cb.get("data") or ""})
                continue
            m = upd.get("message") or {}
            if m.get("text"):
                msgs.append({"uid": (m.get("from") or {}).get("id"),
                             "chat_id": (m.get("chat") or {}).get("id"),
                             "text": m["text"]})
        return msgs

    def _wait_approval(self, chat_id: int, timeout_s: int = 300) -> bool:
        """Block until the operator presses a button OR types yes/no in this chat.

        Returns True for Approve, False for Deny / timeout. Button presses are
        acknowledged via answerCallbackQuery so the button stops spinning."""
        elapsed = 0
        while elapsed < timeout_s:
            for m in self._pull(timeout=20):
                if m["chat_id"] != chat_id or (self.allowed and m["uid"] not in self.allowed):
                    continue
                if m.get("callback_id"):                    # button press
                    decision = m.get("data") == "approve"
                    self._api("answerCallbackQuery", callback_query_id=m["callback_id"],
                              text="Approved" if decision else "Denied")
                    return decision
                # typed-text fallback: "yes"/"no" (and synonyms) still honored
                return m["text"].strip().lower() in _OK
            elapsed += 20
        return False

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
                    self.send(_cid, f"Approve '{name}'?\n{json.dumps(args)[:600]}",
                              reply_markup=_APPROVE_KB)
                    return self._wait_approval(_cid)

                agent = self.agent_factory(approver)
                self.send(chat_id, "…working")
                try:
                    reply = agent.run(text)
                except Exception as e:
                    reply = f"error: {e}"
                self.send(chat_id, reply or "(no answer)")
