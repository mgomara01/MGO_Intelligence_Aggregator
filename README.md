# Alvarez Intelligence Brief (MGO Intelligence Aggregator)

Automated daily intelligence brief for Alvarez Plumbing & Air Conditioning.
Pulls 3-5 stories from 20 registered sources (15 Gmail feeds + 5 web-search
trade/local sources), summarizes with Claude, and renders a branded HTML report.

See the Deployment Handoff doc (sent separately) for full setup instructions:
- Required GitHub Secrets: ANTHROPIC_API_KEY, GMAIL_CREDENTIALS_JSON, DRIVE_FOLDER_ID
- How to add/remove sources via config/sources.json
- Testing checklist before trusting the daily schedule

## Structure
- `config/sources.json` — the 20-source registry (self-service edit point)
- `scripts/generate_brief.py` — main pipeline
- `.github/workflows/intel-brief.yml` — daily cron trigger (14:00 ET)
- `templates/brief_template.html` — branded HTML shell
