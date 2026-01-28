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
from .send_scheduler import (
    SendScheduler,
    detect_timezone,
    get_recipient_local_time,
    is_within_send_window,
    can_send_now
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
    "CampaignManager",
    "SendScheduler",
    "detect_timezone",
    "get_recipient_local_time",
    "is_within_send_window",
    "can_send_now",
]
