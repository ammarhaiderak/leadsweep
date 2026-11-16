# Contributing to LeadSweep

Thanks for helping out! Bug reports, fixes and new platform integrations are all welcome.

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
cd project && npm ci && cd ..
```

Run the API (`uvicorn leadsweep.api:app --reload --port 8000`) and the dashboard (`cd project && npm run dev`) side by side.

## Before opening a pull request

```bash
pytest -m "not live" -q              # backend tests (hermetic, no network)
cd project && npm run build          # type-check + build the dashboard
python -m scripts.secret_scan        # make sure no credentials slipped in
```

- Keep tests hermetic: mock network calls and use the fixtures in `tests/fixtures/`. Anything that needs real network or a browser should be marked `@pytest.mark.live`.
- **Never commit real data or credentials** — no `.env`, `sessions.json`, cookies, databases, or scraped personal data. Use `example.com` addresses in tests.
- New settings go in `leadsweep/config.py` (with a safe default) and `.env.example`.
- Keep pull requests focused; describe what changed and how you tested it.

## Reporting bugs

Open an issue with steps to reproduce, what you expected, and the output of `python -m scripts.doctor`. Scrub cookies, API keys and personal data from logs first.

Security issues: please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
