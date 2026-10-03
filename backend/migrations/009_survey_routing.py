"""
Migration: survey qualification & routing engine (traffic_flow_db)

services/survey_routing.py adds, on url_parameters:
- qualificationAnswers   landing-page answers (employment, occupation, custom q_*)
- prescreen              {surveyNo, passed, reasons[], country, at} for the entry project
- routingSessionId       links every survey attempt of one respondent
- routingAttempt / routedFrom / entryPid   where a routed attempt came from
- firstName / lastName / phone / panelConsent / paidAds   Paid Ads respondents only
and a new collection routing_sessions {country, vendorId, respondentId, attempts[], tried[], final}.

Indexes (all partial, so the 720k existing records cost nothing):
- url_parameters.routingSessionId
- url_parameters.prescreen.surveyNo + prescreen.passed   pre-screen qualification rate
- url_parameters.routedFrom + assignedSurveyId           routed in / out per project
- routing_sessions.createdAt
"""

import logging

from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)

TRAFFIC_DB = "traffic_flow_db"

INDEXES = [
    ("url_parameters", [("routingSessionId", ASCENDING)], "routing_session",
     {"partialFilterExpression": {"routingSessionId": {"$exists": True}}}),
    ("url_parameters", [("prescreen.surveyNo", ASCENDING), ("prescreen.passed", ASCENDING)], "prescreen_survey",
     {"partialFilterExpression": {"prescreen.surveyNo": {"$exists": True}}}),
    ("url_parameters", [("routedFrom", ASCENDING), ("assignedSurveyId", ASCENDING)], "routed_from",
     {"partialFilterExpression": {"routedFrom": {"$exists": True}}}),
    ("routing_sessions", [("createdAt", DESCENDING)], "created", {}),
]


def up(db):
    tdb = db.client[TRAFFIC_DB]
    for coll, keys, name, opts in INDEXES:
        tdb[coll].create_index(keys, name=name, **opts)
    return {"indexes": [f"{c}.{n}" for c, _, n, _ in INDEXES]}


def down(db):
    tdb = db.client[TRAFFIC_DB]
    for coll, _, name, _ in INDEXES:
        try:
            tdb[coll].drop_index(name)
        except Exception as e:
            logger.warning(f"drop_index {coll}.{name}: {e}")
