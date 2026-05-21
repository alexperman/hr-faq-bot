import os
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.services.structured_logger import log_event


router = APIRouter(prefix="/telegram", tags=["telegram"])

# Map bot token → (channel_env_var, chat_id)
_HARDCODED_BOTS = {
    "8526153645:AAFHFDXrVVpIUg-Xw5vXStr56P1QrqROYxQ": ("TELEGRAM_CHAT_INFRA", "184895919"),
    "8896327975:AAGF96IAAnJFwOi7euFc2SjZK1BWuhFz0-U": ("TELEGRAM_CHAT_MEMORY", "184895919"),
    "8926108968:AAHN00pVX2dsAfBDNw0w7QsT0mu4OQ7PaZA": ("TELEGRAM_CHAT_PRODUCT", "184895919"),
    "8732149825:AAHntt58y97KYR8o8iK1vTF1VSi-Wj5WqhI": ("TELEGRAM_CHAT_CRITICAL", "184895919"),
    "8849839799:AAGmWgR7AZgHDWdT7m7M-GOvAf-eyZwTYGI": ("TELEGRAM_CHAT_GROWTH", "184895919"),
}


def _load_env():
    env_path = Path(__file__).resolve().parents[3] / "hermes" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get_config(bot_token: str):
    _load_env()
    # Log what we're working with
    print(f"[TELEGRAM_WEBHOOK] bot_token={bot_token[:15]}...", file=__import__("sys").stderr)
    print(f"[TELEGRAM_WEBHOOK] env TELEGRAM_BOT_TOKEN={os.environ.get('TELEGRAM_BOT_TOKEN','')[:15]}...", file=__import__("sys").stderr)
    # Try env vars first
    token_map = {
        "TELEGRAM_BOT_TOKEN_INFRA": "TELEGRAM_CHAT_INFRA",
        "TELEGRAM_BOT_TOKEN_MEMORY": "TELEGRAM_CHAT_MEMORY",
        "TELEGRAM_BOT_TOKEN_PRODUCT": "TELEGRAM_CHAT_PRODUCT",
        "TELEGRAM_BOT_TOKEN_CRITICAL": "TELEGRAM_CHAT_CRITICAL",
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_CHAT_GROWTH",
    }
    for token_env, channel_env in token_map.items():
        if os.environ.get(token_env, "").strip() == bot_token.strip():
            chat_id = os.environ.get(channel_env, "")
            if chat_id:
                return channel_env, chat_id
    # Fallback to hardcoded
    return _HARDCODED_BOTS.get(bot_token.strip())


_CHANNEL_HANDLERS = {}


def _handle_growth(text: str, chat_id: str) -> str:
    log_event(event="handler_start", handler="growth", text=text[:50], chat_id=chat_id)
    try:
        sys_path = str(Path(__file__).resolve().parents[3])
        import sys
        sys.path.insert(0, sys_path)
        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[3] / "hermes" / ".env"))
        from hermes.tools.telegram import post_message

        # Simple echo/reply handler — agent gets the message and can respond
        reply = f"Growth agent received: {text}"
        post_message('TELEGRAM_CHAT_GROWTH', f"Growth agent received your message: {text}", chat_id=chat_id)
        log_event(event="handler_reply_sent", handler="growth", reply=reply[:100])
        return reply
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_event(event="handler_error", handler="growth", error=str(e))
        return f"Growth agent error: {e}"


def _handle_leads(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[3])
        import sys
        sys.path.insert(0, sys_path)
        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[3] / "hermes" / ".env"))
        from hermes.agents.leads_agent import run_leads_outreach
        import argparse
        args = argparse.Namespace(link='', default_lang='en', limit=30, since_hours=24,
                                 dry_run=False, message=text, chat_id=chat_id)
        run_leads_outreach(args)
        return "Leads agent processed your message"
    except Exception as e:
        return f"Leads agent error: {e}"


def _handle_memory(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[3])
        import sys
        sys.path.insert(0, sys_path)
        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[3] / "hermes" / ".env"))
        from hermes.agents.memory_agent import run_memory_maintenance
        import argparse
        args = argparse.Namespace(message=text, chat_id=chat_id, dry_run=False)
        run_memory_maintenance(args)
        return "Memory agent processed your message"
    except Exception as e:
        return f"Memory agent error: {e}"


def _handle_product(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[3])
        import sys
        sys.path.insert(0, sys_path)
        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[3] / "hermes" / ".env"))
        from hermes.agents.product_agent import run_product_recommendations
        import argparse
        args = argparse.Namespace(message=text, chat_id=chat_id, dry_run=False)
        run_product_recommendations(args)
        return "Product agent processed your message"
    except Exception as e:
        return f"Product agent error: {e}"


def _handle_infra(text: str, chat_id: str) -> str:
    try:
        sys_path = str(Path(__file__).resolve().parents[3])
        import sys
        sys.path.insert(0, sys_path)
        from hermes.tools.env import load_env
        load_env(str(Path(__file__).resolve().parents[3] / "hermes" / ".env"))
        from hermes.agents.infra_agent import run_infra_health_check
        import argparse
        args = argparse.Namespace(message=text, chat_id=chat_id, dry_run=False)
        run_infra_health_check(args)
        return "Infra agent processed your message"
    except Exception as e:
        return f"Infra agent error: {e}"


_CHANNEL_HANDLERS["TELEGRAM_CHAT_GROWTH"] = _handle_growth
_CHANNEL_HANDLERS["TELEGRAM_CHAT_LEADS"] = _handle_leads
_CHANNEL_HANDLERS["TELEGRAM_CHAT_MEMORY"] = _handle_memory
_CHANNEL_HANDLERS["TELEGRAM_CHAT_PRODUCT"] = _handle_product
_CHANNEL_HANDLERS["TELEGRAM_CHAT_INFRA"] = _handle_infra
_CHANNEL_HANDLERS["TELEGRAM_CHAT_CRITICAL"] = _handle_infra


@router.post("/{bot_token}/webhook")
async def telegram_webhook(bot_token: str, request: Request):
    """Receive Telegram updates for a specific bot and dispatch to its agent."""
    config = _get_config(bot_token)
    if not config:
        raise HTTPException(status_code=404, detail="Unknown bot token")

    channel_env, chat_id = config
    log_event(event="telegram_webhook", bot=bot_token[:15], channel=channel_env)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    msg = body.get("message") or body.get("edited_message")
    if not msg:
        return JSONResponse({"ok": True, "handled": "no message"})

    text = (msg.get("text") or msg.get("caption") or "").strip()
    msg_id = msg.get("message_id")

    handler = _CHANNEL_HANDLERS.get(channel_env)
    reply_text = handler(text=text, chat_id=chat_id) if handler else f"No handler for {channel_env}"

    # Send reply
    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={"chat_id": int(chat_id), "text": reply_text,
                                 "reply_to_message_id": msg_id}, timeout=10)
    except Exception as e:
        log_event(event="telegram_reply_failed", error=str(e))

    return JSONResponse({"ok": True})


@router.get("/test")
async def telegram_test():
    """Test endpoint."""
    return JSONResponse({"ok": True, "msg": "telegram router mounted"})