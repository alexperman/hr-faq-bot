"""
Telegram bot webhook router — one bot per agent channel.

Each bot maintains its own conversation history stored in the
TelegramConversation table. When a user messages a bot:
  1. Load history for (bot_token, user_id) from DB
  2. Append user message
  3. Call Qwen with full history as context
  4. Append LLM response
  5. Save updated history
  6. Send LLM response back to user via Telegram sendMessage

Route order matters — specific endpoints MUST be registered before
parameterized ones (e.g. /telegram/test_webhook before /telegram/{token}).
"""
import json
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models import TelegramConversation
from app.services.structured_logger import log_event

router = APIRouter(prefix="/telegram", tags=["telegram"])


# ── Telegram API helpers ───────────────────────────────────────────────────────

TELEGRAM_API = "https://api.telegram.org"

# Qwen via Alibaba MaaS compatible-mode endpoint (OpenAI format)
QWEN_BASE_URL = "https://ws-cr5ewhw1f1dm61i8.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"
QWEN_API_KEY = "sk-ws-djI.Z0t3UeKQo8ZHPwz1T6bgOrY7NhN4P5OPpbY-_rLtpqFWIwwORx9aqZNt4tYRCqKTergKeRWruAxLuXbJ41vpZnZ_Wkg1W8trRPUu9i1RK69o3lgfbNhATTukA1dDyoG0.MEYCIQCsUmWKhD2GzLm6pGKn6s3TNi-SvnVlkwG8ERe6dOlQagIhAM5Iptq9_8bS4KsKm12en5BiziGMp21iNcnXYM25uk1I"


def _get_token_config(bot_token: str) -> dict:
    """
    Map bot_token → (channel_name, chat_id) for routing.
    Each bot token is assigned to exactly one agent channel.
    Falls back to GROWTH for unknown tokens.
    """
    # Token → channel mapping (loaded from env)
    token_map = {
        "8849839799:AAFmWgR7AZgHDWdT7m7M-GOvAf-eyZwTYGI": "GROWTH",
        "8526153645:AAFB6Z1cUq9R-Y5hU6n-r2q7T9-k2b9XQkM": "INFRA",
        "8896327975:AAHgR4lD0aT8S2Y1vN6qX3wZ7-b4c8KjLmN": "MEMORY",
        "8926108968:AAJb5kM2cP7Q9S4Z3tW6xY8aF-d5e9LhOoP": "PRODUCT",
        "8732149825:AACl3nL6dR8T6U2X4sW9yB7cG-e6f0MiQpV": "CRITICAL",
    }
    channel = token_map.get(bot_token, "GROWTH")

    # Per-channel chat IDs (all pointing to Alex's personal Telegram)
    chat_ids = {
        "GROWTH":  "184895919",
        "INFRA":   "184895919",
        "MEMORY":  "184895919",
        "PRODUCT": "184895919",
        "CRITICAL":"184895919",
    }
    return {
        "channel": channel,
        "chat_id": chat_ids.get(channel, "184895919"),
    }


async def _send_telegram_message(bot_token: str, chat_id: str, text: str) -> dict:
    """Send a message via Telegram Bot API."""
    url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


# ── Conversation history helpers ────────────────────────────────────────────────

async def _load_history(bot_token: str, user_id: str) -> list[dict]:
    """Load message history for this bot + user from DB."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TelegramConversation).where(
                TelegramConversation.bot_token == bot_token,
                TelegramConversation.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return []
        try:
            return json.loads(row.history_json)
        except json.JSONDecodeError:
            return []


async def _save_history(bot_token: str, user_id: str, history: list[dict]) -> None:
    """Save message history for this bot + user to DB (upsert)."""
    history_json = json.dumps(history, ensure_ascii=False)
    async with AsyncSessionLocal() as session:
        # Upsert using PostgreSQL ON CONFLICT
        stmt = pg_insert(TelegramConversation).values(
            bot_token=bot_token,
            user_id=user_id,
            history_json=history_json,
            updated_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["bot_token", "user_id"],
            set_={
                "history_json": history_json,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(stmt)
        await session.commit()


async def _call_llm(channel: str, history: list[dict]) -> str:
    """
    Call Qwen via Alibaba MaaS compatible-mode API with conversation history.
    Each channel has a system prompt that defines its agent personality.
    Falls back to a simple echo if QWEN_API_KEY is not configured.
    """
    # System prompts per agent channel
    system_prompts = {
        "GROWTH": (
            "You are the Growth Agent. You help with outreach, lead generation, "
            "marketing automation, and growth strategy. Be direct, action-oriented. "
            "Use concise responses. No filler."
        ),
        "INFRA": (
            "You are the Infra Agent. You help with deployment, DevOps, "
            "infrastructure monitoring, and technical operations. Be precise and technical. "
            "Suggest concrete commands and steps."
        ),
        "MEMORY": (
            "You are the Memory Agent. You help with organizational memory, "
            "knowledge management, decision logging, and project context. "
            "Be thorough and structured."
        ),
        "PRODUCT": (
            "You are the Product Agent. You help with product planning, feature ideas, "
            "roadmap design, and user feedback analysis. Be creative and strategic."
        ),
        "CRITICAL": (
            "You are the Critical Agent. You handle urgent issues, incidents, "
            "escalations, and critical decisions. Be calm, clear, and decisive. "
            "Prioritize speed and accuracy."
        ),
    }
    system = system_prompts.get(channel, system_prompts["GROWTH"])

    # Build messages list from history
    messages = [{"role": "system", "content": system}]
    for entry in history:
        role = "user" if entry.get("from") == "user" else "assistant"
        messages.append({"role": role, "content": entry.get("text", "")})

    if not QWEN_API_KEY:
        # Fallback: echo with channel awareness
        last_msg = history[-1]["text"] if history else ""
        return f"[{channel}] Echo: {last_msg[:100]}"

    payload = {
        "model": "qwen3.5-plus",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 1024,
        "thinking": {"type": "off"},
    }

    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{QWEN_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            # Strip Qwen reasoning block if present (separated by "**Thinking Process:**" or "**<answer>**")
            if "**Thinking Process:**" in raw:
                raw = raw.split("**Thinking Process:**")[-1]
                raw = raw.split("**</answer>**")[-1] if "**</answer>**" in raw else raw
            return raw.strip()
    except Exception as e:
        log_event(event="llm_call_failed", severity="high", channel=channel, error=str(e))
        return "Sorry, I encountered an error processing your request."


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/test_webhook")
async def test_webhook(request: Request):
    """Test endpoint to verify webhook connectivity."""
    return {"ok": True, "message": "webhook working"}


@router.post("/debug_webhook/{token}")
async def debug_webhook(token: str, request: Request):
    """
    Debug endpoint — receives a message from a channel and logs
    the raw message structure so we can extract the real channel chat_id.
    """
    try:
        body = await request.json()
    except Exception:
        return {"error": "invalid JSON"}

    import json
    msg = body.get("message", {})
    chat = msg.get("chat", {})
    forward = msg.get("forward_from_chat", {})

    debug_info = {
        "chat_id": chat.get("id"),
        "chat_type": chat.get("type"),
        "chat_title": chat.get("title"),
        "forward_from_chat_id": forward.get("id"),
        "forward_from_chat_title": forward.get("title"),
        "full_chat": chat,
        "raw_message": msg,
    }

    print(f"DEBUG_WEBHOOK: {json.dumps(debug_info, ensure_ascii=False)}")
    return {"ok": True, "debug": debug_info}


@router.post("/{token}/webhook")
async def handle_webhook(token: str, request: Request):
    """
    Main webhook handler — Telegram sends update here when user messages the bot.
    Path order matters: /test_webhook must come before /{token}/webhook to avoid
    'test_webhook' being interpreted as a bot token.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Extract update fields
    update_id = body.get("update_id", "")
    message = body.get("message", {})
    callback_query = body.get("callback_query", {})

    # Handle callback queries (inline button clicks)
    data = ""
    if callback_query:
        message = callback_query.get("message", {})
        data = callback_query.get("data", "")

    chat = message.get("chat", {})
    user = message.get("from", {})
    text = message.get("text", "")

    # Ignore non-text messages silently
    if not text and not callback_query:
        return {"ok": True}

    chat_id = str(chat.get("id", ""))
    first_name = user.get("first_name", "there")
    message_id = message.get("message_id")

    # Get routing config for this bot
    config = _get_token_config(token)
    channel = config["channel"]

    # DEBUG command: echo back the chat_id so we can capture channel IDs
    if text.strip() == "/debug":
        # Use forward_from_chat.id if this is a forwarded message (from channel)
        # Otherwise fall back to the current chat (direct message)
        debug_chat_id = str(chat.get("id", ""))
        debug_channel = channel
        if message.get("forward_from_chat"):
            debug_chat_id = str(message["forward_from_chat"]["id"])
            debug_channel = f"FORWARDED from {message['forward_from_chat'].get('title', 'unknown')}"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"chat_id={debug_chat_id} channel={debug_channel}"},
            )
        return {"ok": True}

    # DEBUG: log chat_id to find channel ID
    print(f"DEBUG_INFRA_CHAT_ID: {chat_id} | channel: {channel} | text: {text[:50]}")

    # Load existing conversation history
    history = await _load_history(token, chat_id)

    # Append user message to history
    user_msg = {
        "from": "user",
        "text": text or f"[callback: {data}]",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    history.append(user_msg)

    # Call LLM with full context
    response_text = await _call_llm(channel, history)

    # Append assistant response to history
    history.append({
        "from": "assistant",
        "text": response_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Persist updated history
    await _save_history(token, chat_id, history)

    # Send response back to Telegram user
    if response_text:
        # Escape Telegram special characters in Markdown
        escape_chars = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]
        escaped_text = response_text
        for ch in escape_chars:
            escaped_text = escaped_text.replace(ch, f"\\{ch}")

        try:
            await _send_telegram_message(token, chat_id, escaped_text)
        except Exception as e:
            log_event(
                event="telegram_send_failed",
                severity="high",
                token_prefix=token[:10],
                chat_id=chat_id,
                error=str(e),
            )

    log_event(
        event="telegram_webhook_processed",
        channel=channel,
        chat_id=chat_id,
        history_len=len(history),
    )

    return {"ok": True}