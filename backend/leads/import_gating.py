"""
IMPORT GATING & DEDUPLICATION
Clay-like import preview that shows cost, duplicates, and validation
before any data is persisted

Prevents accidental large imports with clear visibility into:
- Total records
- Estimated cost
- Duplicate detection
- Validation results
"""

from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime
from hashlib import md5
import difflib

from .clay_models import (
    ImportSession, DeduplicationRule, SourceType,
    CostControl, CostLedger
)
from .preview_executor import CostEstimator


# ============== DEDUPLICATION ENGINE ==============

class DeduplicationEngine:
    """
    Detect duplicate leads before import
    
    Strategies:
    - Exact matching (email, domain, etc.)
    - Fuzzy matching (names, companies)
    - Composite keys (first_name + last_name + company)
    """
    
    def __init__(self, db_client=None):
        self.db = db_client
    
    def detect_duplicates_in_batch(
        self,
        records: List[Dict[str, Any]],
        rules: List[DeduplicationRule]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        Detect duplicates within a batch of records
        
        Returns:
            - Unique records
            - Duplicates grouped by their key
        """
        
        unique_records = []
        duplicate_groups = {}
        seen_keys = {}
        
        for record in records:
            group_key = self._compute_group_key(record, rules)
            
            if group_key not in seen_keys:
                # First occurrence - it's unique (within batch)
                seen_keys[group_key] = record
                unique_records.append(record)
            else:
                # Duplicate found
                if group_key not in duplicate_groups:
                    duplicate_groups[group_key] = [seen_keys[group_key]]
                duplicate_groups[group_key].append(record)
        
        return unique_records, duplicate_groups
    
    async def detect_duplicates_vs_database(
        self,
        records: List[Dict[str, Any]],
        rules: List[DeduplicationRule],
        collection_name: str = "leads_enriched"
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Detect duplicates between records and existing database
        
        Returns:
            - Records that are new (not duplicates)
            - Duplicate record IDs from database
        """
        
        new_records = []
        duplicate_db_ids = []
        
        for record in records:
            # Check if duplicate exists in DB
            db_record = await self._find_duplicate_in_db(
                record, rules, collection_name
            )
            
            if db_record:
                duplicate_db_ids.append(db_record.get("_id"))
            else:
                new_records.append(record)
        
        return new_records, duplicate_db_ids
    
    def _compute_group_key(
        self,
        record: Dict[str, Any],
        rules: List[DeduplicationRule]
    ) -> str:
        """
        Compute deduplication key for a record
        
        Based on the dedup rules, extracts relevant fields and creates
        a hash key for grouping
        """
        
        # For now, use first rule
        if not rules:
            return md5(str(record).encode()).hexdigest()
        
        rule = rules[0]
        key_parts = []
        
        for field in rule.fields:
            value = self._extract_nested_field(record, field)
            if value:
                key_parts.append(str(value).lower().strip())
        
        key_string = "|".join(key_parts)
        return md5(key_string.encode()).hexdigest()
    
    async def _find_duplicate_in_db(
        self,
        record: Dict[str, Any],
        rules: List[DeduplicationRule],
        collection_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find duplicate in database based on rules
        
        In production, queries MongoDB
        """
        
        if not self.db:
            return None
        
        for rule in rules:
            query = self._build_dedup_query(record, rule)
            
            # Mock database query
            # In production: db[collection_name].find_one(query)
            
        return None
    
    def _build_dedup_query(
        self,
        record: Dict[str, Any],
        rule: DeduplicationRule
    ) -> Dict[str, Any]:
        """Build MongoDB query for deduplication"""
        
        if rule.match_type == "exact":
            # Exact match on all fields
            query = {}
            for field in rule.fields:
                value = self._extract_nested_field(record, field)
                if value:
                    query[field] = value
            return query
        
        elif rule.match_type == "fuzzy":
            # Fuzzy match (would use text search)
            query = {"$text": {"$search": " ".join(
                str(self._extract_nested_field(record, f)) 
                for f in rule.fields if self._extract_nested_field(record, f)
            )}}
            return query
        
        elif rule.match_type == "email_domain":
            # Match email domain
            email = self._extract_nested_field(record, "email")
            if email and "@" in email:
                domain = email.split("@")[1]
                return {"email": {"$regex": f".*@{domain}$"}}
        
        return {}
    
    def _extract_nested_field(self, record: Dict[str, Any], field: str) -> Any:
        """Extract nested field (e.g., 'person.email')"""
        
        parts = field.split(".")
        value = record
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        
        return value
    
    @staticmethod
    def fuzzy_match(str1: str, str2: str, threshold: float = 0.85) -> bool:
        """Check if two strings are similar (for fuzzy matching)"""
        ratio = difflib.SequenceMatcher(None, str1.lower(), str2.lower()).ratio()
        return ratio >= threshold


# ============== IMPORT VALIDATOR ==============

class ImportValidator:
    """Validate records before import"""
    
    def __init__(self):
        self.required_fields = {"email"}  # At minimum, email is required
    
    def validate_batch(
        self,
        records: List[Dict[str, Any]],
        validation_rules: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[str], List[str]]:
        """
        Validate batch of records
        
        Returns:
            - Errors (blocking issues)
            - Warnings (non-blocking issues)
        """
        
        errors = []
        warnings = []
        
        for idx, record in enumerate(records):
            record_errors, record_warnings = self.validate_record(
                record, validation_rules, record_idx=idx
            )
            errors.extend(record_errors)
            warnings.extend(record_warnings)
        
        return errors, warnings
    
    def validate_record(
        self,
        record: Dict[str, Any],
        validation_rules: Optional[Dict[str, Any]] = None,
        record_idx: int = 0
    ) -> Tuple[List[str], List[str]]:
        """Validate single record"""
        
        errors = []
        warnings = []
        
        # Check required fields
        for field in self.required_fields:
            if not record.get(field):
                errors.append(f"Row {record_idx}: Missing required field '{field}'")
        
        # Validate email format
        email = record.get("email")
        if email and not self._is_valid_email(email):
            errors.append(f"Row {record_idx}: Invalid email format: {email}")
        
        # Warn on suspicious data
        if not record.get("company_name"):
            warnings.append(f"Row {record_idx}: Missing company_name")
        
        if not record.get("job_title"):
            warnings.append(f"Row {record_idx}: Missing job_title")
        
        return errors, warnings
    
    @staticmethod
    def _is_valid_email(email: str) -> bool:
        """Basic email validation"""
        return "@" in email and "." in email.split("@")[1]


# ============== IMPORT GATING MANAGER ==============

class ImportGatingManager:
    """
    Manage the import gating workflow
    
    Clay-like flow:
    1. User previews query or selects CSV
    2. System shows: total records, estimated cost, duplicates, validation results
    3. User can set caps (max count, max cost)
    4. User approves import
    5. System executes import with those constraints
    """
    
    def __init__(self, db_client=None):
        self.db = db_client
        self.dedup_engine = DeduplicationEngine(db_client)
        self.validator = ImportValidator()
    
    async def create_import_session(
        self,
        campaign_id: str,
        source_type: SourceType,
        records: List[Dict[str, Any]],
        dedup_rules: List[DeduplicationRule],
        cost_per_record: float = 0.01,
        provider_used: str = "unknown"
    ) -> ImportSession:
        """
        Create an import session - the "gate" before import
        
        Shows user everything they need to see before clicking Import
        """
        
        session = ImportSession(
            campaign_id=campaign_id,
            source_type=source_type,
            dedup_rules=dedup_rules
        )
        
        # Count records
        session.total_records_in_source = len(records)
        
        # Validate
        errors, warnings = self.validator.validate_batch(records)
        session.validation_errors = errors
        session.validation_warnings = warnings
        
        if errors:
            session.validation_status = "failed"
        elif warnings:
            session.validation_status = "warnings"
        else:
            session.validation_status = "valid"
        
        # Detect duplicates within batch
        unique_in_batch, duplicate_groups = self.dedup_engine.detect_duplicates_in_batch(
            records, dedup_rules
        )
        
        # Detect duplicates vs database
        new_records, db_duplicates = await self.dedup_engine.detect_duplicates_vs_database(
            records, dedup_rules
        )
        
        session.estimated_duplicates = len(records) - len(new_records)
        session.estimated_new_leads = len(new_records)
        
        # Cost estimation
        session.estimated_total_cost = CostEstimator.estimate_source_cost(
            source_type, provider_used, session.estimated_new_leads, cost_per_record
        )
        
        # Preview (first 10 records)
        session.preview_records = new_records[:10]
        
        return session
    
    async def approve_import(
        self,
        session: ImportSession,
        approved_by: str,
        max_import_count: Optional[int] = None,
        max_cost: Optional[float] = None
    ) -> ImportSession:
        """
        Approve import with optional caps
        
        User can cap how many leads to import and max cost
        """
        
        session.approved_by = approved_by
        session.approved_at = datetime.utcnow()
        session.status = "approved"
        
        if max_import_count:
            session.max_import_count = max_import_count
        
        if max_cost:
            session.max_cost = max_cost
        
        return session
    
    def validate_against_cost_controls(
        self,
        session: ImportSession,
        cost_controls: CostControl
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate import against cost controls
        
        Check:
        - Hard caps
        - Kill switch
        - Rate limits
        """
        
        # Check daily hard cap
        if cost_controls.daily_hard_cap:
            if session.estimated_total_cost > cost_controls.daily_hard_cap:
                return False, f"Exceeds daily hard cap (${cost_controls.daily_hard_cap})"
        
        # Check monthly hard cap
        if cost_controls.monthly_hard_cap:
            # In production, would sum up costs from today + this month
            if session.estimated_total_cost > cost_controls.monthly_hard_cap:
                return False, f"Would exceed monthly hard cap (${cost_controls.monthly_hard_cap})"
        
        # Check kill switch
        if cost_controls.kill_switch_enabled:
            return False, f"Kill switch engaged: {cost_controls.kill_switch_reason}"
        
        # Check user-defined caps
        if session.max_import_count and session.estimated_new_leads > session.max_import_count:
            return False, f"Exceeds user-defined cap ({session.max_import_count} leads)"
        
        if session.max_cost and session.estimated_total_cost > session.max_cost:
            return False, f"Exceeds user-defined cost cap (${session.max_cost})"
        
        return True, None
    
    def get_import_summary(self, session: ImportSession) -> Dict[str, Any]:
        """
        Get human-readable summary of import (for UI display)
        """
        
        return {
            "total_records": session.total_records_in_source,
            "estimated_new": session.estimated_new_leads,
            "estimated_duplicates": session.estimated_duplicates,
            "estimated_cost": session.estimated_total_cost,
            "validation_status": session.validation_status,
            "validation_errors": session.validation_errors,
            "validation_warnings": session.validation_warnings,
            "preview_records": session.preview_records,
            "approval_status": session.status,
        }


# ============== COST ENFORCEMENT ==============

class CostEnforcer:
    """Enforce cost controls during import"""
    
    def __init__(self):
        self.current_costs = {}  # {campaign_id: total_cost}
    
    def track_cost(
        self,
        campaign_id: str,
        cost: float,
        cost_control: CostControl
    ) -> Tuple[bool, Optional[str]]:
        """
        Track cost and enforce limits
        
        Returns: (should_continue, error_message)
        """
        
        current = self.current_costs.get(campaign_id, 0.0)
        new_total = current + cost
        
        self.current_costs[campaign_id] = new_total
        
        # Check hard cap
        if cost_control.daily_hard_cap and new_total > cost_control.daily_hard_cap:
            cost_control.kill_switch_enabled = True
            cost_control.kill_switch_reason = "Daily hard cap exceeded"
            return False, "Daily hard cap exceeded - import halted"
        
        # Check monthly cap
        if cost_control.monthly_hard_cap and new_total > cost_control.monthly_hard_cap:
            cost_control.kill_switch_enabled = True
            cost_control.kill_switch_reason = "Monthly hard cap exceeded"
            return False, "Monthly hard cap exceeded - import halted"
        
        return True, None
    
    def get_remaining_budget(
        self,
        campaign_id: str,
        cost_control: CostControl
    ) -> float:
        """Get remaining budget for campaign"""
        
        if not cost_control.daily_hard_cap:
            return float('inf')
        
        current = self.current_costs.get(campaign_id, 0.0)
        return max(0, cost_control.daily_hard_cap - current)
