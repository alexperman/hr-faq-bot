"""
backend/app/ package — FastAPI application.
"""

from app.main import app as asgi_app

# Render/gunicorn sometimes expects a WSGI callable (sync worker).
# Wrap the ASGI app as WSGI so it can run under `gunicorn app:app`.
try:
    from asgiref.wsgi import AsgiToWsgi

    app = AsgiToWsgi(asgi_app)
except Exception:
    # If asgiref isn't installed or wrapper fails, fall back to ASGI app.
    app = asgi_app

__all__ = ["app", "asgi_app"]
