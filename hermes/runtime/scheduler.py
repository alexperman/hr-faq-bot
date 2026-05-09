import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from hermes.agents.infra_agent import (
    run_infra_health_check,
    run_infra_deploy_verification,
    run_infra_incident_summarization,
)
from hermes.agents.memory_agent import run_memory_maintenance
from hermes.agents.growth_agent import run_outreach_generation
from hermes.agents.analytics_agent import run_analytics
from hermes.agents.kb_agent import run_kb_assist
from hermes.agents.support_agent import run_support
from hermes.agents.product_agent import run_product_recommendations


class _Args:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run


def main() -> None:
    # Avoid manual endless loops; keep the process alive via an Event.
    scheduler = BackgroundScheduler(timezone="UTC")
    a = _Args(dry_run=False)

    # Every 5 minutes: Render/system health check
    scheduler.add_job(
        run_infra_health_check,
        trigger=IntervalTrigger(minutes=5),
        args=(a,),
        id="infra-health-5m",
        replace_existing=True,
        max_instances=1,
    )

    # Every 15 minutes: webhook verification + deployment sanity
    scheduler.add_job(
        run_infra_deploy_verification,
        trigger=IntervalTrigger(minutes=15),
        args=(a,),
        id="infra-deploy-15m",
        replace_existing=True,
        max_instances=1,
    )

    # Every hour: summarize incidents
    scheduler.add_job(
        run_infra_incident_summarization,
        trigger=IntervalTrigger(hours=1),
        args=(a,),
        id="infra-summarize-1h",
        replace_existing=True,
        max_instances=1,
    )

    # Daily: growth content generation
    scheduler.add_job(
        run_outreach_generation,
        trigger=CronTrigger(hour=2, minute=0),
        args=(a,),
        id="growth-daily",
        replace_existing=True,
        max_instances=1,
    )

    # Daily: memory maintenance (summaries, compression)
    scheduler.add_job(
        run_memory_maintenance,
        trigger=CronTrigger(hour=2, minute=10),
        args=(a,),
        id="memory-daily",
        replace_existing=True,
        max_instances=1,
    )

    # Daily: product recommendations
    scheduler.add_job(
        run_product_recommendations,
        trigger=CronTrigger(hour=2, minute=20),
        args=(a,),
        id="product-daily",
        replace_existing=True,
        max_instances=1,
    )

    # Weekly: analytics (stub) and KB/support (stub)
    scheduler.add_job(
        run_analytics,
        trigger=CronTrigger(day_of_week="mon", hour=2, minute=30),
        args=(a,),
        id="analytics-weekly",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        run_kb_assist,
        trigger=CronTrigger(day_of_week="wed", hour=2, minute=30),
        args=(a,),
        id="kb-weekly",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        run_support,
        trigger=CronTrigger(day_of_week="thu", hour=2, minute=30),
        args=(a,),
        id="support-weekly",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()

    # Keep process alive without a manual loop.
    threading.Event().wait()


if __name__ == "__main__":
    main()
