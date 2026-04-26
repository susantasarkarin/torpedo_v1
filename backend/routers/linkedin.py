"""Compatibility router shim for LinkedIn automation routes."""

try:
    from ..linkedin_automation.router import router
except ImportError:
    from linkedin_automation.router import router


__all__ = ["router"]