# Wire the Telegram gateway

The Telegram channel lets you talk to the agent from your phone, headless, 24/7 — no screen, no
SSH session open. Five steps.

## 1. Make a bot with @BotFather

In Telegram, open a chat with **@BotFather**, send `/newbot`, and answer its two questions (a
display name, then a unique username ending in `bot`). It replies with a **token** that looks like
`123456789:AAByourlongtokenhere`. Keep it private — that token controls the bot.

## 2. Put the token in `.env`

Add the token to `.env` (never to `config.yaml`, never to git):

```
TELEGRAM_BOT_TOKEN=123456789:AAByourlongtokenhere
```

`setup` can do this for you if you answer "yes" to the Telegram question; otherwise add the line
by hand. Keep `.env` `chmod 600`.

## 3. Get your numeric user id from @userinfobot

In Telegram, open a chat with **@userinfobot** and send any message. It replies with your account
details including a numeric **id** (e.g. `987654321`). That's your user id — the allow-list uses
numbers, not usernames.

## 4. Add yourself to the allow-list in `config.yaml`

Enable the channel and list your id under `allowed_users`. Anyone not on this list is ignored —
an empty list means nobody can talk to the bot.

```yaml
channels:
  cli: true
  telegram:
    enabled: true
    allowed_users: [987654321]   # your numeric id from @userinfobot
```

## 5. Run it

```bash
python -m agent telegram
```

It long-polls Telegram and runs each message from an allowed user through the agent loop. On a
24/7 box, run this under systemd so it survives reboots (see [`SETUP.md`](SETUP.md)). Message your
bot from your phone to confirm it answers.

## Approve / Deny buttons

The human-in-the-loop gate works over chat. When the agent wants to do an **`ask_first`** action
(send a message, submit a form, post, publish, pay) it pauses and sends you inline **Approve** /
**Deny** buttons with a summary of what it's about to do. Press one — nothing outward happens until
you do. Typing "yes"/"no" also works as a fallback. Approvals time out (denied) if you don't
respond, so a forgotten request never fires on its own.
