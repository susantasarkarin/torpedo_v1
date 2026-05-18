"""
Smoke: Backend startup integrity
================================
Ensures backend app import path is valid and the FastAPI app object is created.
"""

import importlib

from fastapi import FastAPI


def test_backend_main_app_importable():
    """Import backend.main and assert the FastAPI app object exists."""
    module = importlib.import_module("backend.main")
    app = getattr(module, "app", None)
    assert isinstance(app, FastAPI), "backend.main did not expose a FastAPI app"
