import httpx
from app.config import get_settings
from app.services.structured_logger import log_event


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"


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

    context_text = "\n\n".join(context_docs) if context_docs else "No relevant context provided."

    system_prompt = (
        "You are an HR assistant. Answer ONLY from the provided context documents. "
        "If the answer is not in the context, say you don't know based on the available information. "
        "Be helpful, concise, and professional."
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
