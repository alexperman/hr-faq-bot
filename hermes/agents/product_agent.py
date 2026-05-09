import argparse
from datetime import datetime, timezone

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso


def run_product_recommendations(args: argparse.Namespace) -> None:
    load_env()

    root = memory_root()
    summaries_dir = root / "summaries"
    product_dir = root / "product"

    product_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    # Read the most recent memory summary(s) as evidence.
    summary_files = sorted(summaries_dir.glob("memory_agent_daily_*.json"), key=lambda p: p.stat().st_mtime)
    latest_summary = None
    if summary_files:
        try:
            import json

            latest_summary = json.loads(summary_files[-1].read_text(encoding="utf-8"))
        except Exception:
            latest_summary = None

    recs = []
    if latest_summary:
        ready = latest_summary.get("current_readiness", {})
        paypal_ok = ready.get("paypal_webhook_ok")
        db_ok = ready.get("admin_db_ok")
        kb_docs_total = ready.get("kb_docs_total")

        if db_ok is False:
            recs.append(
                {
                    "priority": "high",
                    "recommendation": "Add a friendly UI banner when the backend is unhealthy (502/health issues), with a retry link.",
                    "why": "Reduce user confusion when Render admin/database connectivity fails.",
                }
            )
        if paypal_ok is False:
            recs.append(
                {
                    "priority": "high",
                    "recommendation": "Improve subscription-page error messaging: explain that webhook verification failed and show 'contact support' CTA.",
                    "why": "PayPal webhook incidents block access (402), and better messaging reduces churn.",
                }
            )
        if kb_docs_total == 0:
            recs.append(
                {
                    "priority": "medium",
                    "recommendation": "Add an onboarding checklist step that confirms KB documents are present before allowing chat.",
                    "why": "Empty corpus leads to poor demo/testing outcomes.",
                }
            )

    if not recs:
        recs = [
            {
                "priority": "low",
                "recommendation": "Add a short 'How answers work' tool-tip in the chat UI to reinforce citations + escalation behavior.",
                "why": "Improves trust and reduces wrong-answer anxiety.",
            }
        ]

    out = {
        "type": "product_agent_recommendations",
        "at": utc_now_iso(),
        "evidence": {"latest_memory_summary_present": latest_summary is not None},
        "recommendations": recs[:3],
        "next": ["Review and implement 1 low-risk copy/UX improvement per week."],
    }

    path = product_dir / f"product_recs_{datetime.now(timezone.utc).date().isoformat()}.json"
    write_json(path, out)

    summary = {
        "type": "product_agent_daily_summary",
        "at": utc_now_iso(),
        "recommendations_written": recs[:3],
        "draft_file": str(path),
    }
    summary_path = root / "summaries" / f"product_agent_summary_{datetime.now(timezone.utc).date().isoformat()}.json"
    write_json(summary_path, summary)

    if not getattr(args, "dry_run", False):
        print(f"[product-agent] wrote {path}")
