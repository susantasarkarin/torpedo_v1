"""
Campaign Module
===============

Email campaign management for cold outreach and automated sequences.
"""

from .models import (
    CampaignStatus,
    RecipientStatus,
    SendStatus,
    SequenceCondition,
    ReplyType,
    EmailTemplate,
    SequenceStep,
    CampaignSettings,
    Campaign,
    CampaignRecipient,
    CampaignSend,
    CampaignManager
)

__all__ = [
    "CampaignStatus",
    "RecipientStatus", 
    "SendStatus",
    "SequenceCondition",
    "ReplyType",
    "EmailTemplate",
    "SequenceStep",
    "CampaignSettings",
    "Campaign",
    "CampaignRecipient",
    "CampaignSend",
    "CampaignManager"
]
