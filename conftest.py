"""
Root pytest configuration.

Puts `backend/` on sys.path so the application's absolute imports
(`from routers import ...`, `from database import ...`) resolve no matter which
directory pytest is invoked from.

This is the first half of TOR-11. The app runs as `uvicorn main:app` with
backend/ as the working directory, which is why 140 files carry a
`try: from .x import y / except ImportError: from x import y` fallback — and
why `backend.main` could not be imported from the repo root at all, so the
app-level smoke test failed by construction and nothing could be tested
in-process.

Fixing the import convention properly means deleting all 338 fallbacks in one
sweep; doing that in the same change as a batch of security fixes would make
both unreviewable. This makes the package importable today, which is what
unblocks the tests, and leaves the fallbacks for a dedicated commit.
"""

import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# A session secret is required at import time (config.py and session_state.py
# both refuse to load without one). Tests never sign anything a real client
# sees, so supply a deterministic value rather than making every developer set
# one — but never a value that could be mistaken for a production secret.
os.environ.setdefault("SESSION_SECRET", "pytest-only-not-a-real-secret")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
