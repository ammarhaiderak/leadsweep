# Security

## Deployment model

LeadSweep is a **self-hosted, single-user tool**. It is designed to run on your own machine or a private server and is **not hardened for exposure to the public internet**:

- Bind it to `127.0.0.1` (the default in `docker-compose.yml`) or put it behind a VPN / authenticating reverse proxy.
- All signed-in accounts are trusted; per-user data isolation is not enforced server-side.
- Set a strong `LEADSWEEP_ADMIN_PASSWORD` and `LEADSWEEP_API_KEY`. No default credentials exist — the owner account is only created from the values in your `.env`.

## Secrets you hold

- `.env`, `sessions.json` / `secrets/` (X cookies), `sessions/` (Telegram), `data/` (database) are all gitignored. Keep them that way.
- X session cookies grant full access to that X account. Use a secondary account.

## Reporting a vulnerability

Please report vulnerabilities privately via GitHub's **"Report a vulnerability"** (Security Advisories) on this repository rather than opening a public issue. Include steps to reproduce and the affected version/commit.
