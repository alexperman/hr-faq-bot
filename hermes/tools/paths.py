from pathlib import Path


def hermes_root() -> Path:
    return Path(__file__).resolve().parents[1]


def memory_root() -> Path:
    return hermes_root() / "memory"
