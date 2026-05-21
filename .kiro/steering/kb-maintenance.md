---
inclusion: manual
---

# KB Maintenance Workflow

When reviewing or maintaining the RelyIQ knowledge base, follow this workflow:

## 1. Audit Current Coverage
Use the `list_documents` MCP tool to see all documents for the tenant.
Check document titles and content for completeness.

## 2. Identify Gaps
Use the `list_escalations` MCP tool with `status: open` to find questions the bot couldn't answer.
These represent missing or incomplete KB entries.

## 3. Suggest Improvements
For each gap:
- Determine if an existing document should be updated or a new one created
- Draft the content with proper citations
- Flag any policy areas that need HR team confirmation

## 4. Validate Accuracy
Cross-reference answers against source documents.
Use `ask_kb` to test that updated content produces correct responses.

## Tools Available
- `get_health` — verify system is operational before making changes
- `list_documents` — audit current KB
- `list_escalations` — find coverage gaps
- `ask_kb` — test answers after updates
