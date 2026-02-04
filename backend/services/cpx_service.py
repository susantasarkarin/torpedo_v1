"""
CPX Research Integration Service

Handles all CPX operations:
1. Survey inventory sync (Phase 1)
2. Respondent allocation (Phase 2)
3. Entry link generation
4. Security & validation
"""

import os
import logging
import hashlib
import httpx
from datetime import datetime
from typing import Dict, Any, Optional, List
from bson import ObjectId
import json

logger = logging.getLogger(__name__)

# CPX Configuration
CPX_APP_ID = os.getenv('CPX_APP_ID', '')
CPX_HASH_KEY = os.getenv('CPX_HASH_KEY', '')
CPX_EXT_USER_ID = os.getenv('CPX_EXT_USER_ID', 'PANEL_88921')
CPX_API_URL = os.getenv('CPX_API_URL', 'https://live-api.cpx-research.com/api/get-surveys.php')
CPX_INDIAN_IP = os.getenv('CPX_INDIAN_IP', '103.21.124.1')  # Default Indian IP for geo-targeting


class CPXService:
    """Service for CPX Research API integration"""
    
    def __init__(self, db):
        """Initialize with MongoDB database reference"""
        self.db = db
        self.cpx_surveys_coll = db['cpx_surveys']
        self.url_parameters_coll = db['url_parameters']  # Traffic records
        self.survey_transactions_coll = db['survey_transactions']
    
    # ============================================
    # PHASE 1: SURVEY INVENTORY SYNC
    # ============================================
    
    def generate_secure_hash(self, ext_user_id: str) -> str:
        """
        Generate CPX secure hash.
        Formula: MD5(ext_user_id + secure_hash_key)
        """
        data = f"{ext_user_id}{CPX_HASH_KEY}"
        return hashlib.md5(data.encode()).hexdigest()
    
    async def fetch_cpx_surveys(self, custom_ext_user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Phase 1: Fetch and sync CPX survey inventory
        
        Flow:
        1. Prepare API request with secure hash
        2. Call CPX API with inventory params (empty subids)
        3. Parse response (handles 3 formats)
        4. Normalize survey data
        5. Upsert to MongoDB
        6. Create/update indexes
        
        Args:
            custom_ext_user_id: Override default ext_user_id for testing
            
        Returns:
            Dict with sync results: count, added, updated, errors
        """
        try:
            logger.info("🔄 Starting CPX survey inventory sync...")
            
            ext_user_id = custom_ext_user_id or CPX_EXT_USER_ID
            secure_hash = self.generate_secure_hash(ext_user_id)
            
            # Step 1: Prepare API request
            params = {
                'app_id': CPX_APP_ID,
                'ext_user_id': ext_user_id,
                'subid_1': '',  # Empty for inventory fetch
                'subid_2': '',  # Empty for inventory fetch
                'output_method': 'api',
                'ip_user': CPX_INDIAN_IP,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'limit': 1000,
                'secure_hash': secure_hash
            }
            
            # Step 2: Call CPX API
            logger.info(f"📡 Calling CPX API: {CPX_API_URL}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(CPX_API_URL, params=params)
                response.raise_for_status()
                data = response.json()
            
            # Step 3: Parse response (handle 3 formats)
            surveys = self._parse_cpx_response(data)
            logger.info(f"✅ Received {len(surveys)} surveys from CPX")
            
            # Step 4: Normalize and upsert
            results = {
                'total_received': len(surveys),
                'added': 0,
                'updated': 0,
                'errors': []
            }
            
            for survey_data in surveys:
                try:
                    normalized = self._normalize_survey(survey_data)
                    survey_id = normalized['_id']
                    
                    # Upsert with $setOnInsert for new surveys
                    result = self.cpx_surveys_coll.update_one(
                        {'_id': survey_id},
                        {
                            '$set': {
                                'title': normalized.get('title'),
                                'loi': normalized.get('loi'),
                                'payout': normalized.get('payout'),
                                'category': normalized.get('category'),
                                'href': normalized.get('href'),
                                'href_new': normalized.get('href_new'),
                                'conversion_rate': normalized.get('conversion_rate'),
                                'country': normalized.get('country', 'ALL'),
                                'provider': 'CPX',
                                'last_updated': datetime.utcnow(),
                                'raw_data': normalized.get('raw_data')
                            },
                            '$setOnInsert': {
                                'created_at': datetime.utcnow(),
                                'click_count': 0,
                                'last_clicked_at': None,
                                'is_active_in_pool': False
                            }
                        },
                        upsert=True
                    )
                    
                    if result.upserted_id:
                        results['added'] += 1
                    elif result.modified_count > 0:
                        results['updated'] += 1
                        
                except Exception as e:
                    error_msg = f"Failed to upsert survey {survey_data.get('id')}: {str(e)}"
                    logger.error(error_msg)
                    results['errors'].append(error_msg)
            
            # Step 5: Create indexes for performance
            self._create_cpx_indexes()
            
            logger.info(f"✅ CPX sync complete: {results['added']} added, {results['updated']} updated")
            return results
            
        except Exception as e:
            logger.error(f"❌ CPX sync error: {e}")
            return {
                'total_received': 0,
                'added': 0,
                'updated': 0,
                'errors': [str(e)]
            }
    
    def _parse_cpx_response(self, data: Dict) -> List[Dict]:
        """
        Parse CPX API response (handles 3 formats)
        Format 1: { "surveys": [...] }
        Format 2: { "count_available_surveys": N, "info": [...] }
        Format 3: { "message_not_found": true } → No surveys
        """
        surveys = []
        
        # Format 1: Direct surveys array
        if 'surveys' in data and isinstance(data['surveys'], list):
            surveys = data['surveys']
        
        # Format 2: info array with count
        elif 'info' in data and isinstance(data['info'], list):
            surveys = data['info']
        
        # Format 3: No surveys found
        elif data.get('message_not_found'):
            surveys = []
        
        return surveys
    
    def _normalize_survey(self, survey_data: Dict) -> Dict:
        """Normalize CPX survey data to internal schema"""
        return {
            '_id': str(survey_data.get('id', '')),  # Survey ID as _id
            'title': survey_data.get('survey_title', 'Untitled Survey'),
            'loi': float(survey_data.get('loi', 0)),  # Length of interview (minutes)
            'payout': float(survey_data.get('payout_publisher_usd', 0)),
            'category': survey_data.get('survey_category', 'General'),
            'href': survey_data.get('href', ''),  # CPX click URL with k= token
            'href_new': survey_data.get('href_new', ''),  # Mobile version
            'conversion_rate': float(survey_data.get('conversion_rate', 0)),  # Success rate %
            'country': survey_data.get('country', 'ALL'),
            'raw_data': survey_data  # Store full response for debugging
        }
    
    def _create_cpx_indexes(self):
        """Create MongoDB indexes for CPX survey filtering/sorting"""
        try:
            # Index for sorting by last_updated (newest first)
            self.cpx_surveys_coll.create_index('last_updated', background=True)
            
            # Index for LOI range filters
            self.cpx_surveys_coll.create_index('loi', background=True)
            
            # Index for payout filters (descending = best payouts first)
            self.cpx_surveys_coll.create_index([('payout', -1)], background=True)
            
            # Index for country filtering
            self.cpx_surveys_coll.create_index('country', background=True)
            
            # Index for category filtering
            self.cpx_surveys_coll.create_index('category', background=True)
            
            # Index for active pool queries
            self.cpx_surveys_coll.create_index('is_active_in_pool', background=True)
            
            # Compound index: (country, last_updated) for common filter + sort
            self.cpx_surveys_coll.create_index([('country', 1), ('last_updated', -1)], background=True)
            
            logger.info("✅ CPX indexes created")
        except Exception as e:
            logger.warning(f"⚠️ Index creation warning: {e}")
    
    # ============================================
    # PHASE 2: RESPONDENT ALLOCATION
    # ============================================
    
    def get_filtered_surveys(
        self,
        max_loi: int = 20,
        min_cpi: float = 1.0,
        min_ir: int = 0,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get filtered surveys based on criteria
        
        Filters:
        - max_loi: Maximum length of interview (minutes)
        - min_cpi: Minimum cost per interview / payout
        - min_ir: Minimum incidence rate / conversion rate
        - is_active_in_pool: Must be activated
        """
        try:
            query = {
                'loi': {'$lte': max_loi},
                'payout': {'$gte': min_cpi},
                'conversion_rate': {'$gte': min_ir},
                'is_active_in_pool': True,
                'href': {'$ne': None, '$ne': ''}  # Must have href to allocate
            }
            
            surveys = list(
                self.cpx_surveys_coll
                .find(query)
                .sort('last_updated', -1)
                .limit(limit)
            )
            
            logger.info(f"📊 Filtered {len(surveys)} surveys: LOI≤{max_loi}, CPI≥{min_cpi}, IR≥{min_ir}")
            return surveys
            
        except Exception as e:
            logger.error(f"Filter surveys error: {e}")
            return []
    
    async def fetch_and_allocate_for_respondent(
        self,
        respondent_id: str,
        client_ip: str,
        user_agent: str
    ) -> Dict[str, Any]:
        """
        Phase 2 allocation: Call CPX API with real IP/fingerprint
        
        Called immediately when respondent clicks PROCEED button.
        Uses real client IP (not hardcoded Indian IP).
        
        Args:
            respondent_id: Unique respondent identifier
            client_ip: Real client IPv4 address
            user_agent: Browser user agent string
            
        Returns:
            Dict with allocated survey and entry link
        """
        try:
            logger.info(f"🔍 Allocating survey for respondent {respondent_id} from IP {client_ip}")
            
            # Generate temporary ext_user_id for this respondent
            import time
            timestamp = int(time.time())
            ext_user_id = f"TEMP_{respondent_id}_{timestamp}"
            
            # Generate secure hash with temporary ext_user_id
            secure_hash = self.generate_secure_hash(ext_user_id)
            
            # Call CPX API with real client IP
            params = {
                'app_id': CPX_APP_ID,
                'ext_user_id': ext_user_id,
                'subid_1': '',  # Will be filled with SFWID later
                'subid_2': '',
                'output_method': 'api',
                'ip_user': client_ip,  # Real client IP
                'user_agent': user_agent,
                'secure_hash': secure_hash
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(CPX_API_URL, params=params)
                response.raise_for_status()
                data = response.json()
            
            # Parse response
            surveys = self._parse_cpx_response(data)
            
            if not surveys:
                logger.warning(f"❌ No surveys available for respondent {respondent_id}")
                return {
                    'success': False,
                    'error': 'No surveys available',
                    'surveys': []
                }
            
            # Return surveys (caller will filter and select)
            normalized_surveys = [self._normalize_survey(s) for s in surveys]
            
            logger.info(f"✅ CPX returned {len(normalized_surveys)} surveys for allocation")
            
            return {
                'success': True,
                'surveys': normalized_surveys,
                'count': len(normalized_surveys)
            }
            
        except Exception as e:
            logger.error(f"❌ Allocation error: {e}")
            return {
                'success': False,
                'error': str(e),
                'surveys': []
            }
    
    def select_random_survey(self, surveys: List[Dict]) -> Optional[Dict]:
        """Randomly select one survey from available list"""
        import random
        if not surveys:
            return None
        return random.choice(surveys)
    
    # ============================================
    # ENTRY LINK GENERATION
    # ============================================
    
    def generate_respondent_entry_link(
        self,
        survey_id: str,
        sfwid: str,
        href: str,
        ext_user_id: str = None
    ) -> str:
        """
        Generate final entry link for respondent
        
        Takes CPX href and appends subid_1=SFWID for tracking
        
        Args:
            survey_id: CPX survey ID
            sfwid: Survey Field Work ID (traffic record _id)
            href: CPX href from survey data (contains k= token)
            ext_user_id: Panel ID (default PANEL_88921)
            
        Returns:
            Full entry link with all parameters
        """
        try:
            ext_user_id = ext_user_id or CPX_EXT_USER_ID
            
            # href already contains k= token and other params
            # Just append subid_1
            separator = '&' if '?' in href else '?'
            entry_link = f"{href}{separator}subid_1={sfwid}"
            
            logger.info(f"🔗 Generated entry link for SFWID {sfwid}")
            return entry_link
            
        except Exception as e:
            logger.error(f"Entry link generation error: {e}")
            return href
    
    # ============================================
    # TRAFFIC RECORD MANAGEMENT
    # ============================================
    
    def create_traffic_record(
        self,
        vendor_id: str,
        country_code: str,
        respondent_id: str,
        client_ip: str,
        ip_source: str,
        device_fingerprint: str,
        fingerprint_source: str,
        fingerprint_components: Dict[str, Any]
    ) -> Optional[str]:
        """
        Create traffic record (SFWID) for respondent
        
        This record links respondent to survey to vendor.
        _id becomes the SFWID used throughout the flow.
        """
        try:
            traffic_record = {
                'vendorId': vendor_id,
                'countryCode': country_code,
                'respondentId': respondent_id,
                'clientIp': client_ip,
                'ipSource': ip_source,
                'deviceFingerprint': device_fingerprint,
                'fingerprintSource': fingerprint_source,
                'fingerprintComponents': fingerprint_components,
                'status': 'INCOMPLETE',
                'createdAt': datetime.utcnow(),
                'cpxPostbackReceived': False,
                'cpxPostbackAt': None,
                'cpxTransId': None,
                'cpxPostbackStatus': None
            }
            
            result = self.url_parameters_coll.insert_one(traffic_record)
            sfwid = str(result.inserted_id)
            
            logger.info(f"✅ Created traffic record: SFWID={sfwid}")
            return sfwid
            
        except Exception as e:
            logger.error(f"Create traffic record error: {e}")
            return None
    
    def assign_survey_to_traffic(
        self,
        sfwid: str,
        survey_id: str,
        entry_link: str
    ) -> bool:
        """Assign survey and entry link to traffic record"""
        try:
            self.url_parameters_coll.update_one(
                {'_id': ObjectId(sfwid)},
                {'$set': {
                    'cpxSurveyId': survey_id,
                    'entryLink': entry_link,
                    'surveyAssignedAt': datetime.utcnow()
                }}
            )
            
            logger.info(f"✅ Assigned survey {survey_id} to SFWID {sfwid}")
            return True
            
        except Exception as e:
            logger.error(f"Assign survey error: {e}")
            return False
    
    # ============================================
    # ANALYTICS & REPORTING
    # ============================================
    
    def get_cpx_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get CPX statistics for reporting"""
        try:
            from datetime import timedelta
            
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Get transaction stats
            stats = {
                'period_days': days,
                'total_completions': 0,
                'total_fraud': 0,
                'total_revenue': 0,
                'average_payout': 0,
                'conversion_rate': 0
            }
            
            # Count completions
            completed = self.survey_transactions_coll.count_documents({
                'status': 'completed',
                'completed_at': {'$gte': cutoff_date}
            })
            
            # Count fraud
            fraud = self.survey_transactions_coll.count_documents({
                'status': 'fraud',
                'created_at': {'$gte': cutoff_date}
            })
            
            # Calculate revenue
            revenue_result = list(self.survey_transactions_coll.aggregate([
                {
                    '$match': {
                        'status': 'completed',
                        'completed_at': {'$gte': cutoff_date}
                    }
                },
                {
                    '$group': {
                        '_id': None,
                        'total_usd': {'$sum': '$amount_usd'},
                        'avg_usd': {'$avg': '$amount_usd'},
                        'count': {'$sum': 1}
                    }
                }
            ]))
            
            if revenue_result:
                revenue_data = revenue_result[0]
                stats['total_revenue'] = revenue_data.get('total_usd', 0)
                stats['average_payout'] = revenue_data.get('avg_usd', 0)
            
            stats['total_completions'] = completed
            stats['total_fraud'] = fraud
            stats['conversion_rate'] = (completed / (completed + fraud) * 100) if (completed + fraud) > 0 else 0
            
            return stats
            
        except Exception as e:
            logger.error(f"Get stats error: {e}")
            return {}


# Global instance
_cpx_service = None


def get_cpx_service(db) -> CPXService:
    """Get or create CPX service instance"""
    global _cpx_service
    if _cpx_service is None:
        _cpx_service = CPXService(db)
    return _cpx_service
