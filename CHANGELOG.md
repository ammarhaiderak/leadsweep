# Changelog

## 1.0.0 — first open-source release

- Project renamed to **LeadSweep** (Python package `leadsweep`, env prefix `LEADSWEEP_`, CLI `leadsweep`).
- Removed all built-in credentials and master tokens; the owner account is created only from `LEADSWEEP_ADMIN_EMAIL` / `LEADSWEEP_ADMIN_PASSWORD`.
- Login sessions now expire after 30 days; plaintext passwords are no longer stored.
- Removed the early-access request/approval flow and pricing page; the owner adds users from the Users page.
- Blank values in `.env` now fall back to defaults instead of failing to start.
- `run.sh` / `stop.sh` launchers for macOS and Linux; CI now runs on Ubuntu, macOS and Windows.
- Default Groq model is now `openai/gpt-oss-120b` (fallback `openai/gpt-oss-20b`), roughly 5× cheaper per lead; Ollama default model is `qwen2.5:3b`.
- `LEADSWEEP_LLM_TOP_N` defaults to 150 per job (was effectively unlimited).
- X scraping skips images, video and fonts by default (`LEADSWEEP_BLOCK_MEDIA`).
- Docker: `mcp-server` mode now starts correctly; `cron` mode is an alias for `loop`.
