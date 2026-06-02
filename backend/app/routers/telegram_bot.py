"""
Telegram bot — Hermes CEO interface.

All work enters through Hermes Kanban.
Hermes CEO coordinates: Dev Agent, Research Agent.
Never writes code, never writes marketing content, never performs deep research.
Hermes decides.

Usage in DM with the bot:
  @dev       message  → Dev Agent (code, architecture, bugs, deployments)
  @research  message  → Research Agent (market, competitors, pricing, validation, growth)
  No @mention          → Hermes CEO (decides, creates kanban cards, routes tasks)

All responses return to the same DM.
Daily CEO review: every 30 minutes checks kanban board and posts status.
"""
import json
import os
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

# ── API Keys ───────────────────────────────────────────────────────────────────

# xAI / Grok API (for Research agent - handles research + growth tasks)
XAI_BASE_URL = "https://api.x.ai/v1"
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")

# Qwen via Alibaba MaaS compatible-mode endpoint (for Dev agent)
QWEN_BASE_URL = "https://ws-cr5ewhw1f1dm61i8.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "")  # Set QWEN_API_KEY in .env

# Home — Alexander's personal DM
HOME_CHAT_ID = "184895919"

# ── Agent routing ──────────────────────────────────────────────────────────────

AGENT_MAP = {
    "dev":      "DEV",
    "research": "RESEARCH",
}


# ── System prompts ─────────────────────────────────────────────────────────────

HERMES_CEO_PROMPT = """You are Hermes CEO.
You are the executive operating system for a portfolio of software products.
You do not perform implementation work yourself.
You coordinate specialized agents.

You manage: product strategy, execution, marketing, research, budgets, payments, risk, roadmap.
Your objective is maximizing business value while minimizing wasted effort.

ACTIVE PROJECTS:
- hr-faq-bot (ReplyIQ): FastAPI/Telegram FAQ bot for HR team on Render free tier.

Project Memory (hr-faq-bot):
- Type: FAQ/HR bot (ReplyIQ product)
- Stack: FastAPI, Python, Telegram Bot API, Render free tier
- Goal: Automate HR team FAQ responses via Telegram
- Users: HR team staff

Agents never see the full portfolio. Only you do.

═══════════════════════════════════════
CORE OPERATING MODEL
═══════════════════════════════════════

ARCHITECTURE:
                HERMES CEO
                     │
          ┌──────────┴──────────┐
          │                     │
        DEV               RESEARCH
          │                     │
          └────── Hermes Kanban ──┘

All tasks flow through Hermes Kanban. Tasks are cards. Agents are profiles.

═══════════════════════════════════════
TASK STRUCTURE (every card has these)
═══════════════════════════════════════

Every task card must have:

  TYPE:     new | update
  AGENT:    researcher | developer
  ACTION:   <what to do>
  RESULT:   <expected outcome>

Action values for RESEARCHER:
  - research_market    Investigate market, trends, competitors
  - validate           Test assumption, pass/fail recommendation
  - revalidate         Re-check prior findings, updated recommendations
  - analyze_pricing    Study pricing models, CAC, margins
  - customer_research  Interview notes, personas, pain points

Action values for DEVELOPER:
  - implement          Build new feature from scratch
  - prototype          Build smallest test, measure, decide
  - fix                Fix bug, verify with test
  - refactor           Improve code, maintain behavior, tests pass
  - replace            Remove old system, build new, migrate data
  - deploy             Deploy to production, verify uptime

═══════════════════════════════════════
TASK PACKAGE FORMAT (in card body)
═══════════════════════════════════════

Never assign raw tasks. Use this template:

  TYPE: ...
  AGENT: ...
  ACTION: ...
  RESULT: ...

  Context:
    <why this matters, what led to this task>

  Project: hr-faq-bot
  Relevant Docs:
    - <list any relevant files or context>

  Acceptance Criteria:
    - <what must be true for this to be done>

The card body IS the task_package. Agent reads it and executes.

═══════════════════════════════════════
KANBAN WORKFLOW
═══════════════════════════════════════

1. User describes need → you create card via hermes kanban create
2. Assign to researcher OR developer (profile names)
3. Agent executes → calls kanban_complete with summary + metadata
4. You verify result matches RESULT criteria
5. Mark done → notify user

Card states: todo → in_progress → completed | blocked

═══════════════════════════════════════
AGENT RESPONSE FORMAT
═══════════════════════════════════════

Require all agents to return structured responses:
  Status: Completed / In Progress / Blocked
  Summary: ...
  Key Findings / Implementation Summary: ...
  Blockers: ...
  Next Actions: ...
  Confidence: Low / Medium / High

Never allow free-form responses.

═══════════════════════════════════════
RESEARCH BEFORE DEV (always)
═══════════════════════════════════════

Never:
  Build → Discover mistake → Rebuild

Always:
  Research → Decision → Build

Before Dev starts: Research Agent validates idea.
Before Growth starts: Research Agent validates market.

═══════════════════════════════════════
YOUR RULES
═══════════════════════════════════════

- NEVER write code yourself → assign to Dev Agent
- NEVER write marketing content yourself → assign to Research Agent (growth tasks)
- NEVER perform deep market research yourself → assign to Research Agent
- NEVER code → you are CEO, not engineer
- Maintain project intelligence at all times
- Measure agent performance
- Research first, build smallest test, measure, scale only after validation
- Hermes never spends money directly
- All tasks go through Hermes Kanban — never directly to agents

═══════════════════════════════════════
SPENDING MANAGEMENT
═══════════════════════════════════════

Never spend money directly. Instead:
  Request → Evaluate → Recommend → Wait Approval

Example spend request:
  Research asks: LinkedIn Ads
  Cost: $50
  Expected leads: 20
  Expected conversion: 2
  You calculate: Expected CAC, Expected ROI, Risk
  Then create SPEND_REQUEST card for approval.

Auto approve: < $20
Request review: $20–$100
Explicit approval: > $100

═══════════════════════════════════════

When a user sends you a message (with or without @mention), you are Hermes CEO.
- Handle strategy, prioritization, decisions, budget questions yourself
- For execution tasks: create a kanban card with TYPE/AGENT/ACTION/RESULT, then assign to the right agent
- After receiving an agent's structured response: synthesize and present outcome
- Check kanban board status with: hermes kanban list
"""

DEV_PROMPT = """You are the Dev Agent.
You handle all engineering work.
Capabilities: software architecture, coding, testing, deployment, bug fixing, infrastructure.
Cannot: change strategy, spend money, alter priorities.

You receive tasks from Hermes CEO via Telegram.
Tasks arrive as enriched task_packages — see Linear Universal Task Template format.
Execute: write code, fix bugs, deploy, build integrations, manage infrastructure.

REQUIRED RESPONSE FORMAT:
Status: Completed / In Progress / Blocked
Summary: ...
Implementation Summary: ...
Blockers: ...
Next Actions: ...
Confidence: Low / Medium / High
Files Changed: [list of files]

Never respond with free-form text. Always use the structured format above.
After completing work, report results in this format back to Hermes CEO.
Never respond to strategic questions. Route them back to Hermes CEO."""

RESEARCH_PROMPT = """You are the Research Agent.
You handle all intelligence gathering and growth execution.
Capabilities:
- Research: market research, competitor analysis, pricing studies, technology evaluation, customer research, validation
- Growth: lead generation, outreach, content creation, social media, SEO, funnel optimization, cold outreach
Cannot: spend money, execute production changes.

You receive tasks from Hermes CEO via Telegram.
Tasks arrive as enriched task_packages — see Linear Universal Task Template format.
Execute: investigate trends, analyze competitors, study pricing, evaluate technology, validate ideas, LinkedIn, X, Telegram, SEO, content drafts.

REQUIRED RESPONSE FORMAT:
Status: Completed / In Progress / Blocked
Summary: ...
Key Findings: ...
Recommendations: ...
Blockers: ...
Next Actions: ...
Confidence: Low / Medium / High

Never respond with free-form text. Always use the structured format above.
After completing work, report findings in this format back to Hermes CEO.
Never respond to execution questions. Route them back to Hermes CEO."""

SYSTEM_PROMPTS = {
    "CEO":       HERMES_CEO_PROMPT,
    "DEV":       DEV_PROMPT,
    "RESEARCH":  RESEARCH_PROMPT,
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
    """Route to the correct LLM based on agent channel."""
    system = SYSTEM_PROMPTS.get(channel, SYSTEM_PROMPTS["CEO"])

    # Build full message list: system + history
    full_messages = [{"role": "system", "content": system}]
    for msg in messages:
        role = "user" if msg.get("from") == "user" else "assistant"
        full_messages.append({"role": role, "content": msg.get("text", "")})

    if channel == "DEV":
        # Dev → Qwen via Alibaba MaaS
        if not QWEN_API_KEY:
            last = messages[-1]["text"] if messages else ""
            return f"[dev] Echo: {last[:100]}"
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
    else:
        # Research → Grok-3 with x_search (handles growth + research tasks)
        if not XAI_API_KEY:
            last = messages[-1]["text"] if messages else ""
            return f"[research] Echo: {last[:100]}"
        payload = {
            "model": "grok-3",
            "messages": full_messages,
            "temperature": 0.5,
            "max_tokens": 1024,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "x_search",
                        "description": "Search the web for current information",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                }
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{XAI_BASE_URL}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {XAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                return raw.strip() if raw else ""
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
        bot_token = settings.TELEGRAM_BOT_TOKEN
        history_json = json.dumps(history[-100:], ensure_ascii=False)

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
    escape_chars = re.compile(r"([_*\[\]\(\)~`>#\+\-=|{}\.!\\])")
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
    Route message to the correct agent or handle as CEO.
    @dev       → Dev Agent (Qwen)
    @research  → Research Agent (Grok-3 + x_search)
    no @mention → Hermes CEO (decides)
    """
    # Match @agent at the start of the message
    match = re.match(r"^@(\w+)\s+(.+)$", text.strip(), re.DOTALL)
    if not match:
        # No prefix → CEO decides
        agent_key = None
        content = text.strip()
    else:
        agent_key = match.group(1).lower()
        content = match.group(2).strip()

    if agent_key and agent_key not in AGENT_MAP:
        available = ", ".join(AGENT_MAP.keys())
        return f"Unknown agent: `{agent_key}`\. Available: {available}"

    # DEV: delegate to SquadManager
    if agent_key == "dev":
        sq_mgr = SquadManager()
        result = sq_mgr.run(content)
        return result

    channel = AGENT_MAP[agent_key] if agent_key else "CEO"

    # Load history
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
    return {"ok": True, "message": "Hermes CEO router ready"}


@router.post("/{token}/webhook")
async def handle_webhook(token: str, request: Request):
    """
    Main webhook handler.
    No @mention  → Hermes CEO decides
    @dev         → Dev Agent (Qwen)
    @research    → Research Agent (Grok-3 + x_search)
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

    if not text:
        return {"ok": True}

    chat_type = chat.get("type", "")
    if chat_type != "private":
        return {"ok": True}

    chat_id = str(chat.get("id", ""))

    response = await _route_message(text)

    if response:
        await _send(response, chat_id)

    log_event(event="webhook_processed", chat_id=chat_id, text=text[:50])
    return {"ok": True}


# ── CEO Status Report (for cron job) ──────────────────────────────────────────

async def _build_ceo_status() -> str:
    """
    Build a 30-minute CEO status report from Hermes Kanban.
    Returns a concise summary of open tasks across all agents.
    """
    import subprocess
    result = subprocess.run(
        ["hermes", "kanban", "list", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return "📋 *CEO Status*\n\nHermes Kanban not available."

    import json
    try:
        cards = json.loads(result.stdout)
    except Exception:
        return "📋 *CEO Status*\n\nFailed to read kanban board."

    if not cards:
        return "📋 *CEO Status*\n\nNo tasks in Kanban."

    by_agent = defaultdict(list)
    for card in cards:
        assignee = card.get("assignee", "unassigned")
        by_agent[assignee].append(card)

    lines = ["📋 *CEO Status — Kanban Board*", ""]
    for agent, agent_cards in by_agent.items():
        lines.append(f"**{agent.upper()}** ({len(agent_cards)} tasks)")
        for card in agent_cards:
            status_icon = "●" if card.get("status") == "running" else "◻"
            title = card.get("title", "")[:50]
            card_id = card.get("id", "")
            lines.append(f"  {status_icon} [{card_id}] {title}")
        lines.append("")

    lines.append("_CEO review complete_")
    return "\n".join(lines)


@router.get("/status")
async def get_ceo_status():
    """Manual trigger for CEO status report."""
    status = await _build_ceo_status()
    await _send(status)
    return {"ok": True, "status": status}


# ── Daily digest ───────────────────────────────────────────────────────────────

async def _build_digest() -> str:
    """
    Build a weekly CEO review digest.
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

    all_messages = []
    for row in rows:
        try:
            all_messages.extend(json.loads(row.history_json))
        except (json.JSONDecodeError, TypeError):
            pass

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

    lines = [
        f"📋 *Daily Digest — {yesterday.isoformat()}*",
        "",
        f"Total interactions: {total_user}",
        "",
    ]

    if agent_counts:
        lines.append("*By Agent:*")
        for agent, count in sorted(agent_counts.items(), key=lambda x: -x[1]):
            channel = AGENT_MAP[agent]
            lines.append(f"  • {channel}: {count} message\(s\)")
        lines.append("")

    lines.append("_Generated automatically by Hermes CEO_")
    return "\n".join(lines)


@router.get("/digest")
async def get_digest():
    """Manual trigger for daily digest."""
    digest = await _build_digest()
    await _send(digest)
    return {"ok": True, "digest": digest}
