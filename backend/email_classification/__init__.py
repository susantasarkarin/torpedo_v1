"""
Email Classification Module
============================

AI-powered email classification and analysis services.

Modules:
- reply_sentiment: Sentiment and intent analysis for campaign replies using GPT-4o-mini
- classification_router: Email routing based on category and content

Usage:
    from backend.email_classification import ReplySentimentClassifier
    
    classifier = ReplySentimentClassifier()
    result = classifier.classify_reply("Thanks! I'd love to schedule a call.")
"""

from .reply_sentiment import (
    ReplySentimentClassifier,
    Sentiment,
    Intent
)

__all__ = [
    "ReplySentimentClassifier",
    "Sentiment",
    "Intent"
]
