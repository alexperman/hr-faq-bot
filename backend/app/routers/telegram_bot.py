import os, json, hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.structured_logger import log_event


router = APIRouter(prefix="/telegram", tags=["telegram"])

# Map bot token suffix → (channel_env_var, agent_handler_fn)
_BOT_HANDLERS = {}


def _load_env():
    """Load hermes .env into os.environ."""
    # The hermes dir is a sibling of backend/, not inside it
    env_path = Path(__file__).resolve().parents[3] / "hermes" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get_bot_config(bot_token: str) -> tuple[str, str] | None:
    """Return (channel_env_var, chat_id) for a given bot token, or None."""
    # Check each bot token env var
    token_map = {
        "TELEGRAM_BOT_TOKEN_INFRA": "TELEGRAM_CHAT_INFRA",
        "TELEGRAM_BOT_TOKEN_MEMORY": "TELEGRAM_CHAT_MEMORY",
        "TELEGRAM_BOT_TOKEN_PRODUCT": "TELEGRAM_CHAT_PRODUCT",
        "TELEGRAM_BOT_TOKEN_CRITICAL": "TELEGRAM_CHAT_CRITICAL",
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_CHAT_GROWTH",  # default growth bot
    }
    for token_env, channel_env in token_map.items():
        if os.environ.get(token_env, "").strip() == bot_token.strip():
            chat_id = os.environ.get(channel_env, "")
            if chat_id:
                return channel_env, chat_id
    return None


def _send_reply(bot_token: str, chat_id: str | int, text: str) -> dict:
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    r = requests.post(url, json={"chat_id": int(chat_id), "text": text[:3500]}, timeout=10)
    return r.json()


def _agent_response(text: str, agent_name: str, channel_env: str) -> str:
    """Send the text via the agent's Telegram channel and return status."""
    import requests
    token = os.environ.get(f"TELEGRAM_BOT_TOKEN_{channel_env.split('_')[-1]}", "")
    if not token:
        # fallback to TELEGRAM_BOT_TOKEN
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get(channel_env, "")
    if not token or not chat_id:
        return f"no token/chat for {channel_env}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": int(chat_id), "text": text[:3500]}, timeout=10)
    return f"sent ({r.status_code})"


# ─── Growth / Leads Agent Handler ───────────────────────────────────────────

def _handle_growth_message(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[2])
        import sys
        sys.path.insert(0, sys_path)
        _load_env()

        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[2] / "hermes" / ".env"))

        from hermes.agents.growth_agent import run_outreach_generation
        import argparse

        args = argparse.Namespace(
            link='', first_name='Alex', default_lang='en',
            limit=30, since_hours=24, dry_run=False,
            message=text, chat_id=chat_id
        )
        run_outreach_generation(args)
        return "Growth agent processed your message"
    except Exception as e:
        return f"Growth agent error: {e}"


# ─── Leads Agent Handler ────────────────────────────────────────────────────

def _handle_leads_message(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[2])
        import sys
        sys.path.insert(0, sys_path)

        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[2] / "hermes" / ".env"))

        from hermes.agents.leads_agent import run_leads_outreach
        import argparse

        args = argparse.Namespace(
            link='', default_lang='en', limit=30, since_hours=24,
            dry_run=False, message=text, chat_id=chat_id
        )
        run_leads_outreach(args)
        return "Leads agent processed your message"
    except Exception as e:
        return f"Leads agent error: {e}"


# ─── Memory Agent Handler ───────────────────────────────────────────────────

def _handle_memory_message(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[2])
        import sys
        sys.path.insert(0, sys_path)

        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[2] / "hermes" / ".env"))

        from hermes.agents.memory_agent import run_memory_maintenance
        import argparse

        args = argparse.Namespace(message=text, chat_id=chat_id, dry_run=False)
        run_memory_maintenance(args)
        return "Memory agent processed your message"
    except Exception as e:
        return f"Memory agent error: {e}"


# ─── Product Agent Handler ─────────────────────────────────────────────────

def _handle_product_message(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[2])
        import sys
        sys.path.insert(0, sys_path)

        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[2] / "hermes" / ".env"))

        from hermes.agents.product_agent import run_product_recommendations
        import argparse

        args = argparse.Namespace(message=text, chat_id=chat_id, dry_run=False)
        run_product_recommendations(args)
        return "Product agent processed your message"
    except Exception as e:
        return f"Product agent error: {e}"


# ─── Infra Agent Handler ────────────────────────────────────────────────────

def _handle_infra_message(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[2])
        import sys
        sys.path.insert(0, sys_path)

        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[2] / "hermes" / ".env"))

        from hermes.agents.infra_agent import run_infra_health_check
        import argparse

        args = argparse.Namespace(message=text, chat_id=chat_id, dry_run=False)
        run_infra_health_check(args)
        return "Infra agent processed your message"
    except Exception as e:
        return f"Infra agent error: {e}"


# ─── Bot routing map ────────────────────────────────────────────────────────

_CHANNEL_HANDLERS = {
    "TELEGRAM_CHAT_GROWTH": _handle_growth_message,
    "TELEGRAM_CHAT_LEADS": _handle_leads_message,
    "TELEGRAM_CHAT_MEMORY": _handle_memory_message,
    "TELEGRAM_CHAT_PRODUCT": _handle_product_message,
    "TELEGRAM_CHAT_INFRA": _handle_infra_message,
    "TELEGRAM_CHAT_CRITICAL": _handle_infra_message,
}


# ─── Webhook endpoints ───────────────────────────────────────────────────────

@router.post("/{bot_token}/webhook")
async def telegram_webhook(bot_token: str, request: Request):
    """Receive Telegram updates for a specific bot and dispatch to its agent."""
    # Load hermes env so bot tokens are available
    env_path = Path(__file__).resolve().parents[3] / "hermes" / ".env"
    _load_env()

    # Debug: log env vars present
    token_map = {
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_CHAT_GROWTH",
        "TELEGRAM_BOT_TOKEN_INFRA": "TELEGRAM_CHAT_INFRA",
        "TELEGRAM_BOT_TOKEN_MEMORY": "TELEGRAM_CHAT_MEMORY",
        "TELEGRAM_BOT_TOKEN_PRODUCT": "TELEGRAM_CHAT_PRODUCT",
        "TELEGRAM_BOT_TOKEN_CRITICAL": "TELEGRAM_CHAT_CRITICAL",
    }
    env_tokens = {k: (v[:10]+"..." if v else "MISSING") for k, v in [(k, os.environ.get(k,"")) for k in token_map]}
    log_event(event="telegram_webhook_hit", path=str(env_path), exists=str(env_path.exists()), env_tokens=env_tokens)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Resolve bot → channel
    config = _get_bot_config(bot_token)
    if not config:
        raise HTTPException(status_code=404, detail="Unknown bot token")

    channel_env, chat_id = config

    # Handle Telegram webhook verification (for setWebhook)
    if body.get("message") is None and body.get("edited_message") is None:
        # Might be a service message or webhook verification
        if "update_id" in body:
            pass  # proceed to process

    msg = body.get("message") or body.get("edited_message")
    if not msg:
        return JSONResponse({"ok": True, "handled": True})

    text = (msg.get("text") or msg.get("caption") or "").strip()
    first_name = msg.get("from", {}).get("first_name", "there")
    msg_id = msg.get("message_id")

    log_event(
        event="telegram_webhook_received",
        bot=channel_env,
        user=first_name,
        text=text[:100],
    )

    # Route to handler
    handler = _CHANNEL_HANDLERS.get(channel_env)
    if not handler:
        reply_text = f"No handler configured for {channel_env}"
    else:
        try:
            reply_text = handler(text=text, chat_id=chat_id)
        except Exception as e:
            reply_text = f"Error: {e}"
            log_event(event="telegram_handler_error", channel=channel_env, error=str(e))

    # Send reply back to Telegram
    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": reply_text,
                "reply_to_message_id": msg_id,
            },
            timeout=10,
        )
    except Exception as e:
        log_event(event="telegram_reply_failed", channel=channel_env, error=str(e))

    return JSONResponse({"ok": True})


@router.get("/{bot_token}/webhook")
async def telegram_webhook_info(bot_token: str):
    """Webhook registration info — set this URL in Telegram bot settings."""
    config = _get_bot_config(bot_token)
    if not config:
        raise HTTPException(status_code=404, detail="Unknown bot token")
    channel_env, chat_id = config
    return {
        "status": "configured",
        "bot": channel_env,
        "webhook_url": f"/telegram/{bot_token}/webhook",
        "chat_id": chat_id,
    }