"""
Backend pytest bootstrap.

`backend/pytest.ini` makes backend/ the rootdir, so pytest only collects
conftest files at or below this directory — a repo-root conftest.py is never
loaded when tests run from here. This is the one that actually takes effect.

Puts backend/ on sys.path so the app's absolute imports (`from routers import
...`) resolve regardless of the invoking directory — the first half of TOR-11,
which is what lets `test_backend_main_app_importable` run at all.
"""

import os
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# config.py and session_state.py both refuse to import without a session
# secret — deliberately, since a well-known default is how an app ends up
# signing production sessions with a public key. Tests need *a* value; give
# them one that could never be mistaken for a real secret.
os.environ.setdefault("SESSION_SECRET", "pytest-only-not-a-real-secret")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
