"""
backend/app/ package — FastAPI core (AlterZahen API).

The Flask app (ReplyIQ) lives in replyiq.py and is re-exported here
so gunicorn app:app can resolve it.
"""
from replyiq import app

__all__ = ["app"]
