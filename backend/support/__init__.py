# backend/support/__init__.py
# Support/Tickets Module

from .models import (
    Ticket, TicketCreate, TicketUpdate, TicketResolve, TicketEscalate,
    TicketStatus, TicketPriority, TicketCategory, TicketSource,
    TicketComment, TicketActivity, TicketStats,
    EscalationLevel, SLAPolicy, SLAStatus, TeamQueue
)
from .service import TicketService
from .sla import SLAManager

__all__ = [
    "Ticket",
    "TicketCreate",
    "TicketUpdate",
    "TicketResolve",
    "TicketEscalate",
    "TicketStatus",
    "TicketPriority",
    "TicketCategory",
    "TicketSource",
    "TicketComment",
    "TicketActivity",
    "TicketStats",
    "EscalationLevel",
    "SLAPolicy",
    "SLAStatus",
    "TeamQueue",
    "TicketService",
    "SLAManager"
]
