import os
from pathlib import Path


def load_env(path: str | None = None) -> None:
    """Load key=value pairs from a .env file into os.environ.

    Minimal parser on purpose (no shell expansion).
    """
    env_path = Path(path) if path else None
    if env_path is None:
        # default: hermes/.env next to this file
        env_path = Path(__file__).resolve().parents[1] / ".env"

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)
