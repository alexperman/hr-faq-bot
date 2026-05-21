---
inclusion: fileMatch
fileMatchPattern: "Procfile*"
---

# Post-Deploy Verification

After any deployment or Procfile change, verify the system is healthy:

## Checklist
1. Run `get_health` MCP tool — confirm DB is connected and status is "ok"
2. Verify the demo tenant data is seeded (list_documents for "demo" tenant)
3. Test a sample question via `ask_kb` with tenant "demo"
4. Check for any open escalations that might indicate issues

## If Health Check Fails
- Check DATABASE_URL is correctly set in environment
- Verify the Render service is running (use hermes infra-agent-health CLI)
- Review recent deploy logs for migration errors

## CLI Alternative
```bash
python -m hermes.cli infra-agent-health
python -m hermes.cli infra-agent-deploy
```
