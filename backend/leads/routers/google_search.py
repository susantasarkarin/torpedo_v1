"""Google Search (legacy) route extracted from leads/router.py (Phase 12b)."""

from fastapi import APIRouter, HTTPException, BackgroundTasks

from ..models import LeadInput
from ..service import import_leads
from ..ingestion import search_linkedin_leads
from ..router_shared import GoogleSearchRequest


def register_google_search_routes(router: APIRouter) -> None:

    @router.post("/import/google-search")
    async def import_from_google_search(
        request: GoogleSearchRequest,
        background_tasks: BackgroundTasks
    ):
        """
        POST /leads/import/google-search
        Search LinkedIn profiles via Google Custom Search and import results.
        """
        try:
            leads = await search_linkedin_leads(
                query=request.query,
                num_results=request.num_results
            )

            if not leads:
                return {"imported": 0, "message": "No LinkedIn profiles found for this query"}

            # Convert to LeadInput format and import
            lead_inputs = [LeadInput(**lead) for lead in leads]
            result = import_leads(lead_inputs)

            return {
                "found": len(leads),
                "imported": result.imported,
                "duplicates": result.duplicates,
                "message": f"Found {len(leads)} leads, imported {result.imported}"
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
