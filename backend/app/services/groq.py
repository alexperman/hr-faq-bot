import httpx
from app.config import get_settings
from app.services.structured_logger import log_event


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

# Rough char limit for context. Llama 3.3 70B supports 128k tokens,
# but Groq enforces payload size limits. ~60k chars ≈ ~15k tokens is safe.
MAX_CONTEXT_CHARS = 60000


def _truncate_context(context_docs: list[str], max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Combine context docs and truncate to fit within token limits."""
    if not context_docs:
        return "No relevant context provided."

    combined = []
    total = 0
    for doc in context_docs:
        if total + len(doc) > max_chars:
            # Add as much of this doc as fits
            remaining = max_chars - total
            if remaining > 200:
                combined.append(doc[:remaining] + "\n[... truncated]")
            break
        combined.append(doc)
        total += len(doc)

    return "\n\n---\n\n".join(combined)


async def ask_groq(question: str, context_docs: list[str]) -> str:
    """
    Query Groq AI for an HR assistant response.

    Args:
        question: The user's question.
        context_docs: List of context documents/chunks to answer from.

    Returns:
        AI response string, or an error/info message if not configured.
    """
    settings = get_settings()

    if not settings.GROQ_API_KEY:
        log_event(event="ai_provider_failure", severity="high", provider="groq", reason="missing_api_key")
        return "AI not configured. Set GROQ_API_KEY environment variable."

    context_text = _truncate_context(context_docs)

    system_prompt = (
        "You are an HR assistant. Answer ONLY from the provided context documents. "
        "If the answer is not in the context, say you don't know based on the available information. "
        "Be helpful, concise, and professional. Cite the relevant section when possible.\n\n"
        "IMPORTANT: After your answer, on a new line, add exactly 2-3 follow-up questions the user might ask next, "
        "based on your answer. Format them on a single line prefixed with 'FOLLOW_UP:' and separated by '|'. "
        "Example: FOLLOW_UP:What are the exceptions to this policy?|How do I apply for this?|Who approves requests?"
    )

    user_prompt = f"Context:\n{context_text}\n\nQuestion: {question}"

    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(GROQ_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        log_event(
            event="ai_provider_failure",
            severity="high",
            provider="groq",
            reason="http_status_error",
            status_code=e.response.status_code,
        )
        return f"Groq API error: {e.response.status_code}"
    except Exception as e:
        log_event(
            event="ai_provider_failure",
            severity="high",
            provider="groq",
            reason="request_failed",
        )
        return "Groq request failed."
