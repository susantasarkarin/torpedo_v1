"""
Smoke: Backend startup integrity
================================

This is the test that stops a deploy coming up with a module missing.

Two imports, deliberately, because they are NOT equivalent:

  * `import main`         — how production runs (uvicorn main:app, cwd=backend,
                            so `routers` is a TOP-LEVEL package)
  * `import backend.main` — how the test suite sees it (backend/ is a package)

The difference is not academic. `routers/campaign_automation.py` carried a bare
`from ..campaigns.automation import ...`, which resolves fine when backend/ is a
package and raises `ImportError: attempted relative import beyond top-level
package` under the real runtime. That router was dead in production while a
package-style import test passed — so the package-style test alone would have
kept saying everything was fine.

Since router mounts now raise instead of printing a warning (TOR-05), either
import failing means the app would refuse to boot. Three other routers were
found dead the same way when this was first made to pass: clay_routes (missing
`Path` import), email_campaigns (undeclared jinja2 dependency), and campaigns
(missing `Body` import).
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_backend_main_app_importable():
    """Package-style import: `backend.main` exposes a FastAPI app."""
    module = importlib.import_module("backend.main")
    app = getattr(module, "app", None)
    assert isinstance(app, FastAPI), "backend.main did not expose a FastAPI app"


def test_production_style_import_mounts_every_router():
    """
    Import exactly the way uvicorn does, in a clean interpreter.

    A subprocess, not an in-process import, because main.py has already been
    imported under its package name by the test above — re-importing it here
    would hit the module cache and prove nothing about the top-level path.
    """
    script = (
        "import sys, os\n"
        "sys.path.insert(0, '.')\n"
        "os.environ.setdefault('SESSION_SECRET', 'pytest-only-not-a-real-secret')\n"
        "os.environ.setdefault('MONGO_URI', 'mongodb://localhost:27017/')\n"
        "os.environ.setdefault('CORS_ORIGINS', 'http://localhost:5173')\n"
        "import main\n"
        "from startup_checks import assert_routes_mounted\n"
        "n = assert_routes_mounted(main.app)\n"
        "print('ROUTES=%d' % n)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        # The app prints check-mark emoji on every mount; on a cp1252 console
        # decoding that output raises before the assertions ever run.
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        pytest.fail(
            "Production-style import failed — the app would not boot.\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    assert "ROUTES=" in result.stdout
    count = int(result.stdout.split("ROUTES=")[1].split()[0])
    # Guards against a router that "mounts" while registering nothing. The real
    # number is ~1050; the floor only needs to catch a whole module vanishing.
    assert count > 900, f"only {count} routes registered — a router is missing"
