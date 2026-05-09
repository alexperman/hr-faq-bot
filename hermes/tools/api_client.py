import os
import requests
from dataclasses import dataclass
from typing import Any


@dataclass
class AdminClient:
    base_url: str
    api_key: str
    timeout_s: int = 20

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def get_json(self, path: str) -> Any:
        url = self.base_url.rstrip("/") + path
        r = requests.get(url, headers=self._headers(), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()


def from_env() -> AdminClient:
    base_url = os.environ.get("REPLYIQ_ADMIN_API_URL", "").strip()
    api_key = os.environ.get("REPLYIQ_ADMIN_API_KEY", "").strip()
    timeout_s = int(os.environ.get("HTTP_TIMEOUT_S", "20"))
    if not base_url or not api_key:
        raise RuntimeError(
            "Missing REPLYIQ_ADMIN_API_URL or REPLYIQ_ADMIN_API_KEY in hermes/.env"
        )
    return AdminClient(base_url=base_url, api_key=api_key, timeout_s=timeout_s)
