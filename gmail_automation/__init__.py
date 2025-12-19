"""
Gmail Automation Application

A modular Python application for Gmail integration with:
- OAuth 2.0 authentication
- Email fetching and parsing
- AI-based categorization and sentiment analysis
- Personalized outbound email generation
- Multiple account/alias management

Author: Gmail Automation Team
Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "Gmail Automation Team"

from .auth import GmailAuthenticator
from .email_fetcher import EmailFetcher
from .categorizer import EmailCategorizer
from .sentiment_analyzer import SentimentAnalyzer
from .email_composer import EmailComposer
from .account_manager import AccountManager

__all__ = [
    "GmailAuthenticator",
    "EmailFetcher", 
    "EmailCategorizer",
    "SentimentAnalyzer",
    "EmailComposer",
    "AccountManager"
]
