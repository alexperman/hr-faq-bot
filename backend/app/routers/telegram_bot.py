"""
Telegram bot — single bot, multi-agent routing via @mention syntax.

Usage in DM with the bot:
  @growth   message  → Growth agent
  @infra    message  → Infra agent
  @memory   message  → Memory agent
  @product  message  → Product agent
  @critical message  → Critical agent
  @dev      message  → Developer agent (delegates to SquadManager per project)

All responses return to the same DM.
Known projects: AlterZahenApp, hr-faq-bot, bloneybears.
No channel setup needed — works entirely in DM.

Daily digest: cron job at 06:00 Berlin (04:00 UTC) posts summary
of previous day's activity to this chat.
"""
import json
import re
import httpx
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, func

import sys
sys.path.insert(0, "/root/.hermes/agents")
from _shared.squad import SquadManager

from app.database import AsyncSessionLocal
from app.models import TelegramConversation
from app.services.structured_logger import log_event
from app.config import get_settings
settings = get_settings()

router = APIRouter(prefix="/telegram", tags=["telegram"])

TELEGRAM_API = "https://api.telegram.org"

# Qwen via Alibaba MaaS compatible-mode endpoint
QWEN_BASE_URL = "https://ws-cr5ewhw1f1dm61i8.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"
QWEN_API_KEY = "sk-ws-djI.Z0t3UeKQo8ZHPwz1T6bgOrY7NhN4P5OPpbY-_rLtpqFWIwwORx9aqZNt4tYRCqKTergKeRWruAxLuXbJ41vpZnZ_Wkg1W8trRPUu9i1RK69o3lgfbNhATTukA1dDyoG0.MEYCIQCsUmWKhD2GzLm6pGKn6s3TNi-SvnVlkwG8ERe6dOlQagIhAM5Iptq9_8bS4KsKm12en5BiziGMp21iNcnXYM25uk1I"

# Home — Alexander's personal DM
HOME_CHAT_ID = "184895919"


# ── Agent routing ──────────────────────────────────────────────────────────────

AGENT_MAP = {
    "growth":   "GROWTH",
    "infra":    "INFRA",
    "memory":   "MEMORY",
    "product":  "PRODUCT",
    "critical": "CRITICAL",
    "dev":      "DEVELOPER",
}


# ── System prompts per agent ───────────────────────────────────────────────────

SYSTEM_PROMPTS = {
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
    "DEVELOPER": (
        "You are the Developer Agent. You delegate coding tasks to project-specific "
        "Squad agents via SquadManager.run(task, project). "
        "Detect project from message text. Known projects: AlterZahenApp, hr-faq-bot, bloneybears. "
        "Be precise — wrong project means wrong codebase context."
    ),
}


# ── LLM ─────────────────────────────────────────────────────────────────────────

def _strip_thinking(raw: str) -> str:
    """Strip Qwen reasoning/thinking blocks from response."""
    if "**Thinking Process:**" in raw:
        raw = raw.split("**Thinking Process:**")[-1]
    if "**</answer>**" in raw:
        raw = raw.split("**</answer>**")[-1]
    return raw.strip()


async def _call_llm(channel: str, messages: list[dict]) -> str:
    """Call Qwen via Alibaba MaaS compatible-mode API."""
    system = SYSTEM_PROMPTS.get(channel, SYSTEM_PROMPTS["GROWTH"])

    # Build full message list: system + history
    full_messages = [{"role": "system", "content": system}]
    for msg in messages:
        role = "user" if msg.get("from") == "user" else "assistant"
        full_messages.append({"role": role, "content": msg.get("text", "")})

    if not QWEN_API_KEY:
        last = messages[-1]["text"] if messages else ""
        return f"[{channel}] Echo: {last[:100]}"

    payload = {
        "model": "qwen3.5-plus",
        "messages": full_messages,
        "temperature": 0.5,
        "max_tokens": 1024,
        "thinking": {"type": "off"},
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{QWEN_BASE_URL}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            return _strip_thinking(raw)
    except Exception as e:
        log_event(event="llm_call_failed", severity="high", channel=channel, error=str(e))
        return "Sorry, I encountered an error. Please try again."


# ── History ────────────────────────────────────────────────────────────────────

async def _load_history(chat_id: str) -> list[dict]:
    """Load all messages for a given chat_id (stored per day-key)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TelegramConversation).where(
                TelegramConversation.user_id == chat_id,
            ).order_by(TelegramConversation.updated_at.desc()).limit(50)
        )
        rows = result.scalars().all()
        # Reverse so oldest first
        messages = []
        seen_keys = set()
        for row in reversed(rows):
            key = f"{row.bot_token}:{row.user_id}:{row.updated_at.date().isoformat()}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            try:
                messages.extend(json.loads(row.history_json))
            except (json.JSONDecodeError, TypeError):
                pass
        return messages


async def _save_history(chat_id: str, history: list[dict]) -> None:
    """Save conversation history. One row per day-key per bot_token."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(timezone.utc).date().isoformat()
        bot_token = settings.TELEGRAM_BOT_TOKEN  # single bot, use same token as key
        history_json = json.dumps(history[-100:], ensure_ascii=False)  # keep last 100 msgs

        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(TelegramConversation).values(
            bot_token=bot_token,
            user_id=chat_id,
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


# ── Telegram sending ───────────────────────────────────────────────────────────

async def _send(text: str, chat_id: str = HOME_CHAT_ID) -> None:
    """Send a message to Telegram."""
    # Escape Telegram MarkdownV2 special chars
    escape_chars = re.compile(r"([_*\[\]\(\)~`>#\+\-\=|{}\.!\\])")
    escaped = escape_chars.sub(r"\\\1", text)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await client.post(
                f"{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": escaped, "parse_mode": "MarkdownV2"},
            )
        except Exception as e:
            log_event(event="telegram_send_failed", severity="medium", chat_id=chat_id, error=str(e))


# ── Routing ────────────────────────────────────────────────────────────────────

async def _route_message(text: str) -> str:
    """
    Parse @agent prefix and route to the correct agent.
    Returns the LLM response text.
    """
    # Match @agent at the start of the message
    match = re.match(r"^@(\w+)\s+(.+)$", text.strip(), re.DOTALL)
    if not match:
        # No prefix → default to GROWTH
        agent_key = "growth"
        content = text.strip()
    else:
        agent_key = match.group(1).lower()
        content = match.group(2).strip()

    if agent_key not in AGENT_MAP:
        available = ", ".join(AGENT_MAP.keys())
        return f"Unknown agent: `{agent_key}`\. Available agents: {available}"

    # DEVELOPER: delegate to SquadManager (persistent per-project qwen serve)
    if agent_key == "dev":
        sq_mgr = SquadManager()
        result = sq_mgr.run(content)
        history.append({"from": "user", "text": content,
                        "timestamp": datetime.now(timezone.utc).isoformat()})
        history.append({"from": "assistant", "text": result,
                        "timestamp": datetime.now(timezone.utc).isoformat()})
        await _save_history(HOME_CHAT_ID, history)
        return result

    channel = AGENT_MAP[agent_key]

    # Load history for this chat
    history = await _load_history(HOME_CHAT_ID)

    # Add current message
    history.append({
        "from": "user",
        "text": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Call LLM
    response = await _call_llm(channel, history)

    # Save updated history
    history.append({
        "from": "assistant",
        "text": response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await _save_history(HOME_CHAT_ID, history)

    return response


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/test_webhook")
async def test_webhook():
    return {"ok": True, "message": "single\-bot router ready"}


@router.post("/{token}/webhook")
async def handle_webhook(token: str, request: Request):
    """
    Main webhook handler — all routing happens in DM with @mention syntax.
    No channel setup needed.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    message = body.get("message", {})
    callback_query = body.get("callback_query", {})

    if callback_query:
        message = callback_query.get("message", {})

    chat = message.get("chat", {})
    user = message.get("from", {})
    text = message.get("text", "")

    # Only handle text messages in private DM (chat_type = "private")
    if not text:
        return {"ok": True}

    chat_type = chat.get("type", "")
    if chat_type != "private":
        # Ignore group/channel messages — we're only handling DMs
        return {"ok": True}

    chat_id = str(chat.get("id", ""))
    first_name = user.get("first_name", "there")

    # Route via @agent prefix
    response = await _route_message(text)

    # Send response back to the DM
    if response:
        await _send(response, chat_id)

    log_event(event="webhook_processed", chat_id=chat_id, text=text[:50])
    return {"ok": True}


# ── Daily digest (for cron job) ────────────────────────────────────────────────

async def _build_digest() -> str:
    """
    Build a concise daily digest from the previous day's conversation history.
    Runs at 06:00 Berlin (04:00 UTC).
    """
    async with AsyncSessionLocal() as session:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        start = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0, tzinfo=timezone.utc)
        end   = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59, tzinfo=timezone.utc)

        result = await session.execute(
            select(TelegramConversation).where(
                TelegramConversation.user_id == HOME_CHAT_ID,
                TelegramConversation.updated_at >= start,
                TelegramConversation.updated_at <= end,
            )
        )
        rows = result.scalars().all()

    if not rows:
        return f"📋 *Daily Digest — {yesterday.isoformat()}*\n\nNo activity yesterday."

    # Collect all messages
    all_messages = []
    for row in rows:
        try:
            all_messages.extend(json.loads(row.history_json))
        except (json.JSONDecodeError, TypeError):
            pass

    # Group by agent channel (look for @growth, @infra etc in user messages)
    agent_counts = defaultdict(int)
    total_user = 0
    for msg in all_messages:
        if msg.get("from") == "user":
            total_user += 1
            text = msg.get("text", "")
            for agent in AGENT_MAP:
                if f"@{agent}" in text.lower():
                    agent_counts[agent] += 1
                    break
        else:
            pass  # count total messages by agent later via history

    # Build digest lines
    lines = [
        f"📋 *Daily Digest — {yesterday.isoformat()}*",
        f"",
        f"Total interactions: {total_user}",
        f""
    ]

    # Per-agent summary
    if agent_counts:
        lines.append("*By Agent:*")
        for agent, count in sorted(agent_counts.items(), key=lambda x: -x[1]):
            channel = AGENT_MAP[agent]
            lines.append(f"  • {channel}: {count} message\(s\)")
        lines.append("")

    # Action items: look for numbered lists or TODO-like content in assistant responses
    lines.append("*Action Items:*")
    action_count = 0
    for msg in all_messages:
        if msg.get("from") == "assistant":
            text = msg.get("text", "")
            # Look for numbered items, TODO items, or lines starting with -
            for line in text.split("\n"):
                stripped = line.strip()
                if any(stripped.startswith(marker) for marker in ["1.", "2.", "3.", "- [ ]", "TODO", "[ ]", "Action:"]):
                    lines.append(f"  • {stripped[:100]}")
                    action_count += 1
                    if action_count >= 10:
                        break
        if action_count >= 10:
            break

    if action_count == 0:
        lines.append("  • No explicit action items found — check agent responses above")

    lines.append("")
    lines.append("_Generated automatically by Hermes_")

    return "\n".join(lines)


@router.get("/digest")
async def get_digest():
    """Manual trigger for daily digest — also callable by cron job."""
    digest = await _build_digest()
    await _send(digest)
    return {"ok": True, "digest": digest}