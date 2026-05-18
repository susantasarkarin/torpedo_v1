"""Shared constants for smoke tests."""
import os

BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")
BACKEND_URL = os.environ.get("SMOKE_BACKEND_URL", "http://localhost:8000")
TEST_USER = os.environ.get("SMOKE_USER", "")
TEST_PASS = os.environ.get("SMOKE_PASS", "")
