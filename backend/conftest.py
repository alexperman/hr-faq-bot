"""
conftest.py — runs automatically when pytest is invoked.
Must unset PORT BEFORE the test module imports `app`, since app.py
reads PORT at import time to decide whether to use /tmp/ for KB storage.
"""
import os
os.environ.pop("PORT", None)
