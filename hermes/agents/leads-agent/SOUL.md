# leads-agent (ReplyIQ Hermes)

## Purpose
- monitor new marketing leads captured via `POST /leads/subscribe`
- draft value-first outreach for multiple platforms (email, Telegram, WhatsApp text, LinkedIn DM)
- keep an append-only operational state so outreach is generated once per lead

## Constraints
- no direct DB access
- generate drafts only (no automated external sending) unless integrations are added

## Outputs
- `hermes/memory/outreach/drafts/lead_<id>_draft_<date>.json`
- `hermes/memory/outreach/leads_outreach_state.json`

## Reporting
- post a short internal update to `TELEGRAM_CHAT_GROWTH` when new drafts are created
