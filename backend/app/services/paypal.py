import httpx
from typing import Optional

from app.config import get_settings

PAYPAL_API: str = ""

__all__ = [
    "get_paypal_access_token",
    "create_subscription",
    "get_subscription_status",
    "cancel_subscription",
    "verify_webhook_signature",
]


def _get_base_url() -> str:
    settings = get_settings()
    if settings.PAYPAL_MODE == "sandbox":
        return "https://api-m.sandbox.paypal.com"
    return "https://api-m.paypal.com"


async def _get_client() -> httpx.AsyncClient:
    global PAYPAL_API
    PAYPAL_API = _get_base_url()
    return httpx.AsyncClient(base_url=PAYPAL_API, timeout=30.0)


async def get_paypal_access_token() -> str:
    """Get PayPal OAuth2 access token."""
    settings = get_settings()
    client = await _get_client()
    
    response = await client.post(
        "/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    
    return response.json()["access_token"]


async def create_subscription(name: str, email: str, plan_id: str, *, return_url: str, cancel_url: str) -> dict:
    """
    Create a PayPal subscription.
    
    Returns dict with 'subscription_id' and 'approval_url'.
    """
    token = await get_paypal_access_token()
    client = await _get_client()
    
    response = await client.post(
        "/v1/billing/subscriptions",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "plan_id": plan_id,
            "subscriber": {
                "name": {"given_name": name},
                "email_address": email,
            },
            "application_context": {
                "brand_name": "RelyIQ",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        },
    )
    response.raise_for_status()
    data = response.json()
    
    # Find approval URL from links array
    approval_url = None
    for link in data.get("links", []):
        if link.get("rel") == "approve":
            approval_url = link["href"]
            break
    
    return {
        "subscription_id": data["id"],
        "approval_url": approval_url,
    }


async def get_subscription_status(subscription_id: str) -> str:
    """Get the status of a PayPal subscription."""
    token = await get_paypal_access_token()
    client = await _get_client()
    
    response = await client.get(
        f"/v1/billing/subscriptions/{subscription_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    
    return response.json()["status"]


async def cancel_subscription(subscription_id: str) -> bool:
    """Cancel a PayPal subscription."""
    token = await get_paypal_access_token()
    client = await _get_client()

    response = await client.post(
        f"/v1/billing/subscriptions/{subscription_id}/cancel",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"reason": "User requested cancellation"},
    )

    if response.status_code == 204:
        return True
    response.raise_for_status()
    return True


async def verify_webhook_signature(
    *,
    transmission_id: str,
    transmission_time: str,
    cert_url: str,
    auth_algo: str,
    webhook_event: dict,
) -> dict:
    """Verify a PayPal webhook using the Notifications API.

    Returns the raw PayPal response JSON.
    Requires `PAYPAL_WEBHOOK_ID` in settings.
    """
    settings = get_settings()
    if not settings.PAYPAL_WEBHOOK_ID:
        raise RuntimeError("PAYPAL_WEBHOOK_ID not configured")

    token = await get_paypal_access_token()
    client = await _get_client()

    response = await client.post(
        "/v1/notifications/verify-webhook-signature",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "transmission_id": transmission_id,
            "transmission_time": transmission_time,
            "cert_url": cert_url,
            "auth_algo": auth_algo,
            "webhook_id": settings.PAYPAL_WEBHOOK_ID,
            "webhook_event": webhook_event,
        },
    )

    response.raise_for_status()
    return response.json()
