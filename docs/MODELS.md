# Pick your brain

The agent is model-agnostic: one line in `config.yaml` (`model.provider`) decides which model
thinks. Swap any time, no code changes. Keys always go in `.env`, never in `config.yaml`.

## Recommendation, in one breath

- **Default: `gemini`.** Google's free tier needs no card, handles long tool chains well, and
  costs nothing to start. This is what `setup` picks for you.
- **Already pay for Claude? `claude-code`.** Uses your existing Claude Code / Max subscription via
  the `claude -p` CLI — no API key, nothing extra on your bill.
- **Want fully offline / private? `ollama`.** Runs a local model on the box, no key, no network,
  no data leaving the machine. Slower and weaker, but yours alone.

Everything else (`openai`, `groq`, `openrouter`, `mistral`, `anthropic`) is there for when you
already have that account or want a specific model.

## The providers

### `gemini` — recommended default
- **What:** Google Gemini, via its OpenAI-compatible endpoint. Default model `gemini-2.5-flash`.
- **Cost:** free tier (no card to start); paid tiers exist if you outgrow it.
- **Key:** `GEMINI_API_KEY` in `.env`.
- **Setup:** make a key at https://aistudio.google.com/apikey, paste it during `setup`.
- **Tradeoff:** best free option, but the free tier has rate limits — a busy day can hit them
  (that's what the fallback chain is for).

### `claude-code` — best if you already pay Claude
- **What:** shells out to the `claude -p` CLI and uses your Claude subscription. Default model
  `claude-opus-4-8`.
- **Cost:** $0 extra — it rides your existing Claude Code / Max subscription, not a metered API.
- **Key:** none. Auth is the logged-in CLI (or `CLAUDE_CODE_OAUTH_TOKEN`).
- **Setup:** install the Claude Code CLI, then run `claude setup-token` once on the box.
- **Tradeoff:** strongest model for the money if you already subscribe, but needs the `claude` CLI
  on the box and is subject to your subscription's usage limits.

### `ollama` — fully offline / private
- **What:** a local model served on the box itself. Default `qwen2.5:3b`.
- **Cost:** free.
- **Key:** none (`OLLAMA_API_KEY` exists but is unused).
- **Setup:** install Ollama, then `ollama pull qwen2.5:3b` (or your chosen model) before first run.
- **Tradeoff:** nothing leaves the machine, but small local models fumble long tool chains —
  treat it as a privacy/offline fallback, not the daily driver. Wants 8 GB+ RAM and ideally a GPU.

### `openai`
- **What:** OpenAI's API. Default model `gpt-4o-mini`.
- **Cost:** paid (pay-per-token).
- **Key:** `OPENAI_API_KEY` in `.env`.
- **Setup:** make a key at https://platform.openai.com/api-keys, paste it during `setup`.
- **Tradeoff:** reliable and capable, but metered — set a spend cap in their console.

### `groq`
- **What:** Groq's fast inference of open models. Default `llama-3.3-70b-versatile`.
- **Cost:** free tier (generous but rate-limited), paid above it.
- **Key:** `GROQ_API_KEY` in `.env`.
- **Setup:** make a key at https://console.groq.com/keys, paste it during `setup`.
- **Tradeoff:** very fast and a strong free fallback, but per-minute token limits are tight —
  it can hit a wall mid-task, so it shines as a fallback rather than primary.

### `openrouter`
- **What:** one API in front of many models (OpenAI, Anthropic, open models, etc.). Default
  `openai/gpt-4o-mini`.
- **Cost:** paid (per-model pricing; some free models exist).
- **Key:** `OPENROUTER_API_KEY` in `.env`.
- **Setup:** make a key at https://openrouter.ai/keys, paste it during `setup`.
- **Tradeoff:** one account to reach almost any model, but you pay a small routing markup and
  depend on a middleman.

### `mistral`
- **What:** Mistral's API. Default `mistral-large-latest`.
- **Cost:** paid.
- **Key:** `MISTRAL_API_KEY` in `.env`.
- **Setup:** make a key at https://console.mistral.ai/api-keys, paste it during `setup`.
- **Tradeoff:** solid European option (data-residency story), but metered and a smaller ecosystem.

### `anthropic`
- **What:** Anthropic's native Messages API. Default `claude-sonnet-4-6`.
- **Cost:** paid (pay-per-token).
- **Key:** `ANTHROPIC_API_KEY` in `.env`.
- **Setup:** make a key at https://console.anthropic.com, paste it during `setup`.
- **Tradeoff:** top-tier reasoning, but it's the metered API — if you already have a Claude
  subscription, prefer `claude-code` to avoid paying twice.

## The fallback chain

The primary provider's free tier can run out (quota, rate limit). Rather than die, the agent
falls through to the next brain in line. In `config.yaml`:

```yaml
model:
  provider: gemini
  model: gemini-2.5-flash

fallback:
  - { provider: groq,   model: llama-3.3-70b-versatile }
  - { provider: ollama, model: qwen2.5:3b }   # local, no rate limit (needs Ollama installed)
```

How it works: each call tries `model` first; on a provider error it tries each `fallback` entry
top to bottom until one answers. A sensible chain is **cloud primary -> cloud fallback -> local
ollama** so the agent stays alive even fully offline — it just gets slower, not dead. Remove the
ollama line if you have no local model.

## Switching brains

Re-run `python -m agent setup`, or edit `model.provider` + `model.model` in `config.yaml` and put
the new key in `.env`. Then verify before trusting it:

```bash
python -m agent selftest
```
