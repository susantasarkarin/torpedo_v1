from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class StartSurveyRequest(BaseModel):
    """Sent when a new respondent starts the survey."""
    pass  # no input needed; server generates respondent_id


class StartSurveyResponse(BaseModel):
    respondent_id: str
    first_question_id: str


class AnswerPayload(BaseModel):
    respondent_id: str
    question_id: str
    answer: Any  # code(s), text, or grid dict


class RoutingDecision(BaseModel):
    action: str  # "next" | "skip_to" | "terminate" | "complete"
    next_question_id: Optional[str] = None
    skip_to_question_id: Optional[str] = None
    reason: Optional[str] = None
    active_categories: Optional[list] = None   # set on Q8 response
    redirect_url: Optional[str] = None


class QuotaStatus(BaseModel):
    quota_key: str
    current: int
    limit: int
    is_full: bool


class ResumeSurveyResponse(BaseModel):
    respondent_id: str
    responses: dict
    current_question_id: Optional[str] = None
    active_categories: Optional[list] = None
    status: str  # "in_progress" | "completed" | "terminated"
