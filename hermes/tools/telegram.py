import os
import requests


def _get_token(channel_env_var: str = "TELEGRAM_BOT_TOKEN") -> str:
    # Channel-specific token overrides
    if channel_env_var == "TELEGRAM_CHAT_INFRA":
        token = os.environ.get("TELEGRAM_BOT_TOKEN_INFRA", "").strip()
        if token:
            return token
    if channel_env_var == "TELEGRAM_CHAT_MEMORY":
        token = os.environ.get("TELEGRAM_BOT_TOKEN_MEMORY", "").strip()
        if token:
            return token
    if channel_env_var == "TELEGRAM_CHAT_PRODUCT":
        token = os.environ.get("TELEGRAM_BOT_TOKEN_PRODUCT", "").strip()
        if token:
            return token
    if channel_env_var == "TELEGRAM_CHAT_CRITICAL":
        token = os.environ.get("TELEGRAM_BOT_TOKEN_CRITICAL", "").strip()
        if token:
            return token
    if channel_env_var == "TELEGRAM_CHAT_GROWTH":
        token = os.environ.get("TELEGRAM_BOT_TOKEN_GROWTH", "").strip()
        if token:
            return token
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _channel_from_env(var_name: str) -> str | None:
    v = os.environ.get(var_name, "").strip()
    return v or None


def post_message(channel_env_var: str, text: str) -> None:
    """Post a message to a Telegram channel/chat.

    If TELEGRAM_BOT_TOKEN or the target channel id is not set, this is a no-op.
    """
    token = _get_token(channel_env_var)
    chat_id = _channel_from_env(channel_env_var)
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text[:3500]},
            timeout=10,
        ).raise_for_status()
    except Exception:
        # Never leak secrets; silently ignore Telegram failures.
        return
