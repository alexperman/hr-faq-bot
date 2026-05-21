---
inclusion: manual
---

# Escalation Triage Workflow

When reviewing and prioritizing open escalations (questions the bot couldn't answer):

## 1. Load Open Escalations
Use the `list_escalations` MCP tool with `status: open` to get all unresolved items.

## 2. Categorize by Priority
- **High**: Questions about benefits, pay, legal compliance
- **Medium**: Policy clarifications, process questions
- **Low**: General inquiries, nice-to-have info

## 3. Draft Responses
For each escalation:
- Check if the answer exists in KB but wasn't matched (search issue)
- If answer exists: suggest KB improvement to prevent future escalations
- If answer doesn't exist: draft a response and suggest adding to KB

## 4. Recommend KB Updates
Group escalations by topic and suggest new documents or document updates
that would prevent similar escalations in the future.

## Authentication
This skill requires a RelyIQ API key with scope `skill`.
Set `RELYIQ_API_KEY` in your environment.
