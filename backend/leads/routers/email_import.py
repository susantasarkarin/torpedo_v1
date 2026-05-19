"""
leads/routers/email_import.py
==============================
Route group: Gmail/IMAP account management, email lead extraction,
email aliases detection/management.
Registered via register_email_import_routes(router) in leads/router.py.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..imap_leads_service import (
    import_leads_from_emails, get_email_leads, get_segment_statistics,
    get_imap_accounts, add_imap_account, remove_imap_account,
    test_imap_connection, EmailSegment, imap_accounts_collection,
    detect_aliases_from_sent, add_detected_aliases
)
from ..router_shared import email_metadata_collection


def register_email_import_routes(router: APIRouter):

    # ============== EMAIL/IMAP LEADS ENDPOINTS (Issue 7 - IMAP/SMTP) ==============

    class EmailImportRequest(BaseModel):
        """Request model for email leads import via IMAP"""
        account_emails: Optional[List[str]] = None  # None = all accounts
        max_emails: int = 500
        since_days: int = 30
        segments: Optional[List[str]] = None  # Filter by segment

    class IMAPAccountCreate(BaseModel):
        """Request model for adding IMAP account"""
        email: str
        password: str  # App password for Gmail
        display_name: str = ""
        imap_server: Optional[str] = None
        imap_port: Optional[int] = None
        smtp_server: Optional[str] = None
        smtp_port: Optional[int] = None
        use_ssl: bool = True
        is_default: bool = False
        skip_validation: bool = False  # Skip IMAP connection test if True

    def get_mailboxes_from_stored_emails() -> List[Dict[str, Any]]:
        """
        Get mailbox accounts from stored emails in torpedo_gmail.email_metadata.
        Discovers mailboxes by analyzing sent emails (outbound direction).
        """
        pipeline = [
            {"$match": {"direction": "outbound"}},
            {"$group": {
                "_id": "$mailbox_id",
                "from_email": {"$first": "$from_email"},
                "from_name": {"$first": "$from_name"},
                "email_count": {"$sum": 1},
                "last_email": {"$max": "$timestamp"}
            }},
            {"$sort": {"email_count": -1}}
        ]

        results = list(email_metadata_collection.aggregate(pipeline))

        mailboxes = []
        for r in results:
            total_count = email_metadata_collection.count_documents({"mailbox_id": r["_id"]})
            mailboxes.append({
                "email": r["from_email"],
                "display_name": r.get("from_name") or r["from_email"].split("@")[0],
                "mailbox_id": r["_id"],
                "email_count": total_count,
                "sent_count": r["email_count"],
                "last_email": r.get("last_email"),
                "source": "stored_emails"
            })
        return mailboxes

    @router.get("/gmail/accounts")
    async def get_email_accounts_endpoint():
        """GET /leads/gmail/accounts — Get all available email accounts (IMAP + stored emails)."""
        imap_accounts = get_imap_accounts()
        stored_mailboxes = get_mailboxes_from_stored_emails()
        imap_emails = {a["email"].lower() for a in imap_accounts}
        all_accounts = imap_accounts.copy()
        for mailbox in stored_mailboxes:
            if mailbox["email"].lower() not in imap_emails:
                all_accounts.append(mailbox)
        return {"accounts": all_accounts, "total": len(all_accounts)}

    @router.post("/gmail/accounts")
    async def add_email_account_endpoint(request: IMAPAccountCreate):
        """POST /leads/gmail/accounts — Add a new IMAP email account."""
        result = add_imap_account(
            email_address=request.email,
            password=request.password,
            display_name=request.display_name,
            imap_server=request.imap_server,
            imap_port=request.imap_port,
            smtp_server=request.smtp_server,
            smtp_port=request.smtp_port,
            use_ssl=request.use_ssl,
            is_default=request.is_default,
            skip_validation=request.skip_validation
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result

    @router.delete("/gmail/accounts/{email}")
    async def remove_email_account_endpoint(email: str):
        """DELETE /leads/gmail/accounts/{email} — Remove an IMAP email account."""
        result = remove_imap_account(email)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        return result

    @router.post("/gmail/accounts/{email}/test")
    async def test_email_account_endpoint(email: str):
        """POST /leads/gmail/accounts/{email}/test — Test IMAP connection for an account."""
        result = test_imap_connection(email)
        return result

    @router.post("/gmail/import")
    async def import_email_leads_endpoint(
        request: EmailImportRequest,
        background_tasks: BackgroundTasks
    ):
        """POST /leads/gmail/import — Import leads from email accounts via IMAP."""
        try:
            result = import_leads_from_emails(
                account_emails=request.account_emails,
                max_emails=request.max_emails,
                since_days=request.since_days,
                segments=request.segments
            )
            return {
                "success": result.get("success", True),
                "emails_processed": result.get("emails_processed", 0),
                "leads_imported": result.get("leads_imported", 0),
                "duplicates": result.get("duplicates", 0),
                "errors": result.get("errors"),
                "message": result.get("message", "Import completed")
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ============== EMAIL EXTRACTION FROM MONGODB ==============

    class EmailExtractRequest(BaseModel):
        """Request to extract leads from stored emails in MongoDB"""
        account_emails: Optional[List[str]] = None
        max_emails: int = 100
        segments: Optional[List[str]] = None
        enrichment_phases: Optional[dict] = None  # {basic, names, company, domain}

    def extract_domain_from_email(email: str) -> Optional[str]:
        """Extract domain from email address"""
        if not email or "@" not in email:
            return None
        return email.split("@")[1].lower()

    def extract_company_from_domain(domain: str) -> Optional[str]:
        """Try to extract company name from domain"""
        if not domain:
            return None
        common_tlds = ['.com', '.net', '.org', '.io', '.co', '.ai', '.tech', '.dev']
        company = domain
        for tld in common_tlds:
            if company.endswith(tld):
                company = company[:-len(tld)]
                break
        if '.' in company:
            parts = company.split('.')
            company = parts[-1] if len(parts[-1]) > 2 else parts[0]
        return company.title() if company else None

    def split_name(full_name: str) -> tuple:
        """Split full name into first and last name"""
        if not full_name:
            return None, None
        parts = full_name.strip().split()
        if len(parts) == 0:
            return None, None
        if len(parts) == 1:
            return parts[0], None
        return parts[0], " ".join(parts[1:])

    def extract_name_from_email_header(from_header: str) -> tuple:
        """Extract name and email from 'Name <email@domain.com>' format"""
        import re
        if not from_header:
            return None, None
        match = re.match(r'^"?([^"<]+)"?\s*<?([^>]+@[^>]+)>?$', from_header.strip())
        if match:
            name = match.group(1).strip().strip('"')
            email = match.group(2).strip()
            if '@' in name or name.lower() == email.lower():
                name = None
            return name, email
        if '@' in from_header:
            return None, from_header.strip()
        return None, None

    @router.post("/emails/extract")
    async def extract_leads_from_stored_emails(request: EmailExtractRequest):
        """
        DEPRECATED: Manual lead extraction is no longer needed.

        Leads are now automatically extracted during Gmail sync.
        See: gmail_workspace_service_vm.py -> _save_email_metadata()

        This endpoint now triggers a backfill for any emails that weren't
        processed by the automatic ingestion.
        """
        from ..canonical_ingestion import ingest_lead, extract_lead_from_email

        try:
            query = {
                "direction": "inbound",
                "$or": [
                    {"lead_extracted": {"$exists": False}},
                    {"lead_extracted": False}
                ]
            }

            if request.account_emails:
                query["to_email"] = {"$in": [e.lower() for e in request.account_emails]}

            if request.segments:
                query["ai_category"] = {"$in": request.segments}

            emails = list(email_metadata_collection.find(query).limit(request.max_emails))

            extracted = 0
            duplicates = 0
            errors = 0

            for email_doc in emails:
                try:
                    payload = extract_lead_from_email(email_doc)
                    if not payload:
                        continue

                    # skip_classification=True: avoid synchronous OpenAI calls per-lead which
                    # would cause Cloudflare 524 timeout for large batches.
                    result = ingest_lead(
                        payload=payload,
                        source='gmail',
                        source_detail='backfill_extraction',
                        skip_classification=True
                    )

                    if result['success']:
                        if result['action'] == 'inserted':
                            extracted += 1
                        elif result['action'] in ('skipped', 'updated'):
                            duplicates += 1
                        email_metadata_collection.update_one(
                            {"_id": email_doc["_id"]},
                            {"$set": {"lead_extracted": True, "lead_id": result.get('lead_id')}}
                        )
                    else:
                        errors += 1
                except Exception:
                    errors += 1
                    continue

            return {
                "success": True,
                "message": "DEPRECATED: Use automatic ingestion. This endpoint backfills missed emails.",
                "emails_processed": len(emails),
                "leads_extracted": extracted,
                "duplicates": duplicates,
                "errors": errors
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/gmail/leads")
    async def get_email_leads_endpoint(
        segment: Optional[str] = None,
        page: int = Query(1, ge=1),
        limit: int = Query(50, ge=1, le=200)
    ):
        """GET /leads/gmail/leads — Get leads extracted from emails with filtering."""
        skip = (page - 1) * limit
        leads = get_email_leads(segment=segment, limit=limit, skip=skip)
        return {"leads": leads, "total": len(leads), "page": page, "limit": limit}

    @router.get("/gmail/segments")
    async def get_email_segments_endpoint():
        """GET /leads/gmail/segments — Get available segments and their lead counts."""
        stats = get_segment_statistics()
        segments = [
            {"id": s.value, "name": s.value.replace("_", " ").title(), "count": stats.get(s.value, 0)}
            for s in EmailSegment
        ]
        return {"segments": segments}

    # ============== EMAIL ALIASES ENDPOINTS ==============

    class AliasCreate(BaseModel):
        """Request model for adding an alias"""
        email: str
        name: Optional[str] = ""

    @router.get("/gmail/accounts/{account_email}/aliases")
    async def get_account_aliases(account_email: str):
        """GET /leads/gmail/accounts/{account_email}/aliases — Get all aliases for an IMAP account."""
        account = imap_accounts_collection.find_one({"email": account_email})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"aliases": account.get("aliases", [])}

    @router.post("/gmail/accounts/{account_email}/aliases")
    async def add_account_alias(account_email: str, alias: AliasCreate):
        """POST /leads/gmail/accounts/{account_email}/aliases — Add an alias to an IMAP account."""
        account = imap_accounts_collection.find_one({"email": account_email})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        aliases = account.get("aliases", [])
        if any(a["email"].lower() == alias.email.lower() for a in aliases):
            raise HTTPException(status_code=400, detail="Alias already exists")

        new_alias = {
            "email": alias.email,
            "name": alias.name or "",
            "is_primary": False,
            "added_at": datetime.utcnow().isoformat()
        }
        aliases.append(new_alias)
        imap_accounts_collection.update_one(
            {"email": account_email},
            {"$set": {"aliases": aliases}}
        )
        return {"success": True, "alias": new_alias, "message": "Alias added successfully"}

    @router.delete("/gmail/accounts/{account_email}/aliases/{alias_email}")
    async def remove_account_alias(account_email: str, alias_email: str):
        """DELETE /leads/gmail/accounts/{account_email}/aliases/{alias_email}"""
        account = imap_accounts_collection.find_one({"email": account_email})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        aliases = account.get("aliases", [])
        original_count = len(aliases)
        aliases = [a for a in aliases if a["email"].lower() != alias_email.lower()]

        if len(aliases) == original_count:
            raise HTTPException(status_code=404, detail="Alias not found")

        imap_accounts_collection.update_one(
            {"email": account_email},
            {"$set": {"aliases": aliases}}
        )
        return {"success": True, "message": "Alias removed"}

    @router.post("/gmail/accounts/{account_email}/aliases/detect")
    async def detect_account_aliases(account_email: str):
        """POST /leads/gmail/accounts/{account_email}/aliases/detect — Auto-detect aliases from sent emails."""
        result = detect_aliases_from_sent(account_email)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result

    @router.post("/gmail/accounts/{account_email}/aliases/sync")
    async def sync_account_aliases(account_email: str):
        """POST /leads/gmail/accounts/{account_email}/aliases/sync — Auto-detect and add aliases."""
        result = add_detected_aliases(account_email)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
