"""
Intelligence Module
===================

Competitive intelligence and advanced analytics for campaign optimization.

Components:
- CompetitorTracker: Track and analyze competitor mentions in replies
"""

from .competitor_tracker import (
    CompetitorTracker,
    detect_competitors_in_reply,
    log_competitor_mention
)

__all__ = [
    "CompetitorTracker",
    "detect_competitors_in_reply",
    "log_competitor_mention"
]
