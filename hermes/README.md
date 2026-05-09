# Hermes (ReplyIQ)

Operational agent suite for **ReplyIQ / hr-faq-bot**.

This folder implements a *project-local* Hermes that runs on your VPS (via systemd timers), not the global OpenClaw Hermes.

## Responsibilities
- infra-agent: monitor Render health + deployment signals, summarize incidents
- memory-agent: persistent operational memory (local JSON/markdown)
- growth-agent: generate multilingual outreach drafts (EN/ES/DE)
- analytics-agent: growth analytics collection (via admin APIs when available)
- kb-agent: KB maintenance suggestions (via admin APIs when available)
- support-agent: incident summaries and recommended product actions

## Security model
- Hermes may only call ReplyIQ **authenticated** admin APIs.
- Hermes never connects to or mutates the production DB directly.

## Configuration
Create `hermes/.env` from `hermes/.env.example`.
