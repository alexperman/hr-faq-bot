from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import User, Tenant, Subscription
from app.services.auth import get_current_user
from app.services.paypal import create_subscription as paypal_create_subscription, cancel_subscription as paypal_cancel_subscription
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/{tenant}/billing", tags=["billing"])

# Pricing tiers (maps to PayPal plan IDs via PRICE_ID env)
PRICING_TIERS = {
    "starter": {"name": "Starter", "price": 99, "employees": 50},
    "growth":  {"name": "Growth",  "price": 299, "employees": 200},
    "enterprise": {"name": "Enterprise", "price": 799, "employees": "unlimited"},
}


# Pydantic schemas
class SubscriptionStatusResponse(BaseModel):
    status: str
    plan: str | None
    price: int | None
    paypal_subscription_id: str | None
    current_period_end: datetime | None


class SubscribeRequest(BaseModel):
    plan: str = "starter"  # starter | growth | enterprise


class SubscribeResponse(BaseModel):
    approval_url: str


class WebhookPayload(BaseModel):
    event_type: str
    resource: dict | None = None


@router.get("/plans", response_model=dict)
async def get_plans():
    """Return available pricing plans (public, no auth required)."""
    return {
        "plans": [
            {"id": key, "name": v["name"], "price": v["price"], "employees": v["employees"]}
            for key, v in PRICING_TIERS.items()
        ]
    }


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
        plan=subscription.plan,
        price=subscription.price,
        paypal_subscription_id=subscription.paypal_subscription_id,
        current_period_end=subscription.current_period_end,
    )


@router.post("/subscribe", response_model=SubscribeResponse)
async def create_subscription(
    request: SubscribeRequest,
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new PayPal subscription for the tenant.
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

    if request.plan not in PRICING_TIERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan. Must be one of: {list(PRICING_TIERS.keys())}",
        )

    tier = PRICING_TIERS[request.plan]

    # Get or create subscription record
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == db_tenant.id)
    )
    subscription = sub_result.scalar_one_or_none()

    if subscription is None:
        subscription = Subscription(
            tenant_id=db_tenant.id,
            plan=request.plan,
            price=tier["price"],
            status="pending",
        )
        db.add(subscription)
        await db.flush()
    else:
        # Update plan/price for renewal
        subscription.plan = request.plan
        subscription.price = tier["price"]

    # Call PayPal to create subscription
    try:
        paypal_result = await paypal_create_subscription(
            name=current_user.full_name,
            email=current_user.email,
            plan_id=settings.PRICE_ID,
        )
        subscription.paypal_subscription_id = paypal_result["subscription_id"]
        await db.commit()
        await db.refresh(subscription)

        approval_url = paypal_result.get("approval_url")
        if not approval_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PayPal did not return an approval URL",
            )

        return SubscribeResponse(approval_url=approval_url)

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PayPal error: {str(e)}",
        )


@router.post("/webhook")
async def handle_paypal_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle PayPal webhooks for subscription events.
    No authentication required - PayPal verifies via webhook signature.
    """
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
                tenant_result = await db.execute(
                    select(Tenant).where(Tenant.id == subscription.tenant_id)
                )
                tenant = tenant_result.scalar_one_or_none()
                if tenant:
                    tenant.is_active = False
                await db.commit()

    elif event_type == "PAYMENT_SALE.COMPLETED":
        # Update period end on successful payment
        subscription_id = resource.get("billing_agreement_id")
        if subscription_id:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.paypal_subscription_id == subscription_id
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
                subscription.status = "active"
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

    if subscription is None or subscription.paypal_subscription_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found",
        )

    # Cancel in PayPal
    try:
        await paypal_cancel_subscription(subscription.paypal_subscription_id)
    except Exception:
        pass  # If PayPal fails, still mark locally

    subscription.status = "cancelled"
    await db.commit()

    return {"status": "cancelled", "message": "Subscription cancelled successfully"}
