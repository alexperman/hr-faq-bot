from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import User, Tenant, Subscription
from app.services.auth import get_current_user
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/{tenant}/billing", tags=["billing"])


# Pydantic schemas
class SubscriptionStatusResponse(BaseModel):
    status: str
    paypal_subscription_id: str | None
    paypal_plan_id: str | None
    current_period_end: datetime | None


class SubscribeResponse(BaseModel):
    approval_url: str


class WebhookPayload(BaseModel):
    event_type: str
    resource: dict | None = None


@router.get("/status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current subscription status for the tenant.
    Requires JWT authentication.
    """
    # Validate tenant access
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()

    if db_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )

    # Get subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == db_tenant.id)
    )
    subscription = sub_result.scalar_one_or_none()

    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found for this tenant",
        )

    return SubscriptionStatusResponse(
        status=subscription.status,
        paypal_subscription_id=subscription.paypal_subscription_id,
        paypal_plan_id=subscription.paypal_plan_id,
        current_period_end=subscription.current_period_end,
    )


@router.post("/subscribe", response_model=SubscribeResponse)
async def create_subscription(
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new PayPal subscription for the tenant.
    Requires JWT authentication.
    Returns the PayPal approval URL to redirect the user.
    """
    # Validate tenant access
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()

    if db_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )

    # Get or create subscription record
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == db_tenant.id)
    )
    subscription = sub_result.scalar_one_or_none()

    if subscription is None:
        subscription = Subscription(
            tenant_id=db_tenant.id,
            status="pending",
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)

    # In production, this would call PayPal API to create a subscription
    # and return the approval URL. For now, return a placeholder.
    # Example PayPal flow:
    # 1. Create subscription with PayPal API
    # 2. Get approval link from response
    # 3. Return approval_url to frontend
    approval_url = f"https://www.sandbox.paypal.com/checkoutnow?token={subscription.id}"

    return SubscribeResponse(approval_url=approval_url)


@router.post("/webhook")
async def handle_paypal_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle PayPal webhooks for subscription events.
    No authentication required - PayPal verifies via webhook signature.
    """
    # In production, verify PayPal webhook signature
    body = await request.json()
    event_type = body.get("event_type")
    resource = body.get("resource", {})

    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
        subscription_id = resource.get("id")
        if subscription_id:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.paypal_subscription_id == subscription_id
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                subscription.status = "active"
                subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
                await db.commit()

    elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
        subscription_id = resource.get("id")
        if subscription_id:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.paypal_subscription_id == subscription_id
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                subscription.status = "cancelled"
                await db.commit()

    elif event_type == "BILLING.SUBSCRIPTION.EXPIRED":
        subscription_id = resource.get("id")
        if subscription_id:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.paypal_subscription_id == subscription_id
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                subscription.status = "expired"
                # Also deactivate the tenant
                tenant_result = await db.execute(
                    select(Tenant).where(Tenant.id == subscription.tenant_id)
                )
                tenant = tenant_result.scalar_one_or_none()
                if tenant:
                    tenant.is_active = False
                await db.commit()

    return {"status": "ok"}


@router.post("/cancel")
async def cancel_subscription(
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel the current subscription for the tenant.
    Requires JWT authentication.
    """
    # Validate tenant access
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()

    if db_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )

    # Get subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == db_tenant.id)
    )
    subscription = sub_result.scalar_one_or_none()

    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found for this tenant",
        )

    # In production, this would call PayPal API to cancel the subscription
    subscription.status = "cancelled"
    await db.commit()

    return {"status": "cancelled", "message": "Subscription cancelled successfully"}
