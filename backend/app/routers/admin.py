import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import get_settings
from app.database import get_db
from app.models import WebhookEvent, Subscription, Tenant, Document, Lead, FunnelEvent
from app.services.rate_limit import get_rate_limit_stats
from app.services.auth import get_auth_failure_stats
from app.services.kb_monitor import get_kb_failure_stats
from app.services.structured_logger import log_audit
settings = get_settings()
router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin auth not configured",
        )

    expected = f"Bearer {settings.ADMIN_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


APP_START_TIME = datetime.now(timezone.utc)


async def _db_ping(db: AsyncSession) -> bool:
    try:
        await db.execute(select(1))
        return True
    except Exception:
        return False


async def _latest_webhook(db: AsyncSession) -> WebhookEvent | None:
    result = await db.execute(
        select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/health")
async def admin_health(_: None = Depends(require_admin)):
    return {"status": "ok"}


@router.get("/system/health")
async def system_health(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Operational health: DB + PayPal webhook + KB readiness + rate-limit anomalies."""

    db_ok = await _db_ping(db)

    latest = await _latest_webhook(db)
    paypal_ok = bool(latest and latest.verified)
    paypal_received_at = latest.received_at.isoformat() if latest and latest.received_at else None

    # KB readiness signals (aggregate only, no tenant details)
    docs_total = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    docs_last_updated_at_row = await db.execute(select(func.max(Document.updated_at)))
    docs_last_updated_at = docs_last_updated_at_row.scalar_one()
    docs_last_updated_iso = docs_last_updated_at.isoformat() if docs_last_updated_at else None

    # Rate limit anomalies
    rl = get_rate_limit_stats()

    # Active subscriptions count (aggregate)
    active_subs = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(Subscription.status == "active")
        )
    ).scalar_one()

    # Tenant health aggregates (active tenants with empty/stale KB)
    active_tenant_ids = (
        select(Subscription.tenant_id)
        .where(Subscription.status == "active")
        .subquery()
    )

    active_tenants_with_docs = (
        await db.execute(
            select(func.count(func.distinct(Document.tenant_id))).where(
                Document.tenant_id.in_(active_tenant_ids)
            )
        )
    ).scalar_one()

    active_tenants_empty_kb = int(active_subs - active_tenants_with_docs)

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    stale_tenant_ids_subq = (
        select(Document.tenant_id)
        .where(Document.tenant_id.in_(active_tenant_ids))
        .group_by(Document.tenant_id)
        .having(func.max(Document.updated_at) < cutoff_7d)
        .subquery()
    )
    active_tenants_stale_kb_over_7d = (
        await db.execute(select(func.count()).select_from(stale_tenant_ids_subq))
    ).scalar_one()

    kb_warning = None
    if active_subs > 0 and docs_total == 0:
        kb_warning = "Active tenants exist but documents corpus is empty"

    auth_stats = get_auth_failure_stats()
    kb_ingest_stats = get_kb_failure_stats()

    return {
        "ok": db_ok,
        "db": {"ok": db_ok},
        "api": {"ok": True, "start_time": APP_START_TIME.isoformat()},
        "auth": auth_stats,
        "rate_limit": {
            "exceeded_last_60s": rl.get("exceeded_last_60s"),
            "exceeded_last_24h": rl.get("exceeded_last_24h"),
        },
        "kb": {
            "docs_total": docs_total,
            "docs_last_updated_at": docs_last_updated_iso,
            "warning": kb_warning,
        },
        "kb_ingest": kb_ingest_stats,
        "tenants": {
            "active_subscriptions": active_subs,
            "active_tenants_empty_kb": active_tenants_empty_kb,
            "active_tenants_stale_kb_over_7d": active_tenants_stale_kb_over_7d,
        },
        "paypal": {
            "latest_webhook_verified": paypal_ok,
            "latest_webhook_event_type": latest.event_type if latest else None,
            "latest_webhook_received_at": paypal_received_at,
            "webhook_processing_ok": paypal_ok,
        },
    }


@router.get("/system/logs")
async def system_logs(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Structured operational logs (safe aggregates + recent webhook verification attempts)."""

    # Recent webhook verification attempts (do not include full payload)
    result = await db.execute(
        select(WebhookEvent)
        .order_by(WebhookEvent.received_at.desc())
        .limit(20)
    )
    events = result.scalars().all()

    rl = get_rate_limit_stats()

    return {
        "recent_webhook_events": [
            {
                "paypal_event_id": ev.paypal_event_id,
                "event_type": ev.event_type,
                "verified": ev.verified,
                "verification_status": ev.verification_status,
                "verification_detail": ev.verification_detail,
                "received_at": ev.received_at.isoformat(),
            }
            for ev in events
        ],
        "recent_rate_limit_exceeds": rl.get("recent_exceeded_events", []),
    }


@router.get("/system/stats")
async def system_stats(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate stats (no tenant-level data)."""

    tenants_total = (await db.execute(select(func.count()).select_from(Tenant))).scalar_one()
    subs_by_status = await db.execute(
        select(Subscription.status, func.count()).group_by(Subscription.status)
    )
    subs_by_status_rows = subs_by_status.all()

    docs_total = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    docs_last_updated_at_row = await db.execute(select(func.max(Document.updated_at)))
    docs_last_updated_at = docs_last_updated_at_row.scalar_one()

    rl = get_rate_limit_stats()

    latest = await _latest_webhook(db)

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(days=1)

    paypal_failures_24h = (
        await db.execute(
            select(func.count()).select_from(WebhookEvent).where(
                WebhookEvent.received_at >= cutoff_24h,
                WebhookEvent.verified == False,  # noqa: E712
            )
        )
    ).scalar_one()

    auth_stats = get_auth_failure_stats()
    kb_ingest_stats = get_kb_failure_stats()

    active_subs = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(Subscription.status == "active")
        )
    ).scalar_one()

    active_tenant_ids = (
        select(Subscription.tenant_id)
        .where(Subscription.status == "active")
        .subquery()
    )

    active_tenants_with_docs = (
        await db.execute(
            select(func.count(func.distinct(Document.tenant_id))).where(
                Document.tenant_id.in_(active_tenant_ids)
            )
        )
    ).scalar_one()

    active_tenants_empty_kb = int(active_subs - active_tenants_with_docs)

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    stale_tenant_ids_subq = (
        select(Document.tenant_id)
        .where(Document.tenant_id.in_(active_tenant_ids))
        .group_by(Document.tenant_id)
        .having(func.max(Document.updated_at) < cutoff_7d)
        .subquery()
    )
    active_tenants_stale_kb_over_7d = (
        await db.execute(select(func.count()).select_from(stale_tenant_ids_subq))
    ).scalar_one()

    return {
        "tenants_total": tenants_total,
        "subscriptions_by_status": [
            {"status": s, "count": c} for (s, c) in subs_by_status_rows
        ],
        "tenants": {
            "active_subscriptions": active_subs,
            "active_tenants_empty_kb": active_tenants_empty_kb,
            "active_tenants_stale_kb_over_7d": active_tenants_stale_kb_over_7d,
        },
        "documents_total": docs_total,
        "documents_last_updated_at": docs_last_updated_at.isoformat() if docs_last_updated_at else None,
        "rate_limit": {
            "exceeded_last_60s": rl.get("exceeded_last_60s"),
            "exceeded_last_24h": rl.get("exceeded_last_24h"),
        },
        "auth": auth_stats,
        "kb_ingest": kb_ingest_stats,
        "paypal": {
            "latest_webhook_verified": bool(latest and latest.verified),
            "latest_webhook_event_type": latest.event_type if latest else None,
            "latest_webhook_received_at": latest.received_at.isoformat() if latest else None,
            "paypal_webhook_failures_last_24h": paypal_failures_24h,
            "webhook_id_configured": bool(settings.PAYPAL_WEBHOOK_ID),
        },
    }


@router.get("/deploy/status")
async def deploy_status(
    _: None = Depends(require_admin),
):
    """Deployment status snapshot from environment variables."""

    env_keys = [
        "RENDER_SERVICE_NAME",
        "RENDER_INSTANCE_ID",
        "RENDER_REGION",
        "RENDER_GIT_COMMIT",
        "RENDER_GIT_BRANCH",
        "RENDER_BUILD_ID",
    ]

    env = {k: os.environ.get(k) for k in env_keys if os.environ.get(k)}

    return {
        "service": settings.APP_URL,
        "app_start_time": APP_START_TIME.isoformat(),
        "environment": env,
    }


@router.get("/paypal/status")
async def paypal_status(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    latest = await _latest_webhook(db)

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(days=1)

    webhook_received_last_24h = (
        await db.execute(
            select(func.count()).select_from(WebhookEvent).where(
                WebhookEvent.received_at >= cutoff_24h
            )
        )
    ).scalar_one()

    last_verified = bool(latest and latest.verified)

    return {
        "paypal_mode": settings.PAYPAL_MODE,
        "webhook_id_configured": bool(settings.PAYPAL_WEBHOOK_ID),
        "latest_webhook": {
            "event_type": latest.event_type if latest else None,
            "verified": latest.verified if latest else None,
            "verification_status": latest.verification_status if latest else None,
            "verification_detail": latest.verification_detail if latest else None,
            "received_at": latest.received_at.isoformat() if latest else None,
        },
        "webhook_received_last_24h": webhook_received_last_24h,
        "webhook_processing_ok": last_verified,
    }


@router.get("/tenants/summary")
async def tenants_summary(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-level readiness summary (aggregates only, no tenant-specific data)."""

    tenants_total = (await db.execute(select(func.count()).select_from(Tenant))).scalar_one()
    active_tenants = (await db.execute(select(func.count()).select_from(Tenant).where(Tenant.is_active == True))).scalar_one()  # noqa: E712

    active_subs = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(Subscription.status == "active")
        )
    ).scalar_one()

    active_tenant_ids = (
        select(Subscription.tenant_id)
        .where(Subscription.status == "active")
        .subquery()
    )

    active_tenants_with_docs = (
        await db.execute(
            select(func.count(func.distinct(Document.tenant_id))).where(
                Document.tenant_id.in_(active_tenant_ids)
            )
        )
    ).scalar_one()

    active_tenants_empty_kb = int(active_subs - active_tenants_with_docs)

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    stale_tenant_ids_subq = (
        select(Document.tenant_id)
        .where(Document.tenant_id.in_(active_tenant_ids))
        .group_by(Document.tenant_id)
        .having(func.max(Document.updated_at) < cutoff_7d)
        .subquery()
    )
    active_tenants_stale_kb_over_7d = (
        await db.execute(select(func.count()).select_from(stale_tenant_ids_subq))
    ).scalar_one()

    kb_ingest = get_kb_failure_stats()

    return {
        "tenants_total": tenants_total,
        "active_tenants": active_tenants,
        "active_subscriptions": active_subs,
        "active_tenants_empty_kb": active_tenants_empty_kb,
        "active_tenants_stale_kb_over_7d": active_tenants_stale_kb_over_7d,
        "kb_ingest_failures_recent": kb_ingest.get("failures_total_recent"),
    }


@router.post("/kb/reindex")
async def kb_reindex(
    _: None = Depends(require_admin),
    approval: str | None = Header(default=None, alias="X-Approval"),
):
    """Reindex KB (medium-risk, requires explicit approval).

    For the current MVP, retrieval uses keyword search, so this endpoint is a safe
    no-op while still providing the operational hook and audit logging.
    """

    if approval != "true":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval required")

    # Audit log only (no secrets, no tenant data)
    log_audit(action="kb_reindex", approval=approval)

    return {
        "status": "noop",
        "reason": "keyword_search_only_currently_no_index_to_rebuild",
    }


@router.get("/leads/recent")
async def leads_recent(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    since_hours: int = 24,
):
    """Return recent marketing leads for outreach orchestration (emails only)."""

    # Clamp to keep cheap and predictable
    limit = max(1, min(200, int(limit)))
    since_hours = max(1, min(168, int(since_hours)))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    result = await db.execute(
        select(Lead)
        .where(Lead.created_at >= cutoff)
        .order_by(Lead.created_at.desc())
        .limit(limit)
    )
    leads = result.scalars().all()

    return {
        "leads": [
            {
                "id": l.id,
                "email": l.email,
                "source": l.source,
                "created_at": l.created_at.isoformat(),
            }
            for l in leads
        ]
    }


@router.get("/funnel/recent")
async def funnel_recent(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = 200,
    since_hours: int = 168,
):
    """Return recent funnel events (instrumentation for growth/funnel intelligence)."""

    limit = max(1, min(1000, int(limit)))
    since_hours = max(1, min(720, int(since_hours)))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    result = await db.execute(
        select(FunnelEvent)
        .where(FunnelEvent.created_at >= cutoff)
        .order_by(FunnelEvent.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()

    return {
        "events": [
            {
                "id": ev.id,
                "event_type": ev.event_type,
                "tenant_id": ev.tenant_id,
                "user_id": ev.user_id,
                "lead_id": ev.lead_id,
                "created_at": ev.created_at.isoformat(),
                "payload": ev.payload,
            }
            for ev in events
        ]
    }
