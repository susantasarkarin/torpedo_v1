"""
CPX Research Database Schema & Indexes

Defines MongoDB collections, schemas, and indexes for CPX integration.
Runs on application startup to ensure proper schema.
"""

import logging
from datetime import datetime
from typing import Optional
from pymongo import ASCENDING, DESCENDING, TEXT

logger = logging.getLogger(__name__)


class CPXDatabaseSetup:
    """Setup and manage CPX database schema"""
    
    def __init__(self, db):
        """Initialize with MongoDB database"""
        self.db = db
    
    def setup_collections(self):
        """Create and configure all CPX-related collections"""
        try:
            logger.info("🗄️  Setting up CPX database collections...")
            
            # 1. CPX Surveys Collection
            self._setup_cpx_surveys()
            
            # 2. Traffic Records Collection (url_parameters)
            self._setup_url_parameters()
            
            # 3. Survey Transactions Collection
            self._setup_survey_transactions()
            
            # 4. CPX Postback Logs Collection
            self._setup_cpx_postback_logs()
            
            # 5. CPX Filter Settings Collection
            self._setup_cpx_filter_settings()
            
            logger.info("✅ CPX database setup complete")
            
        except Exception as e:
            logger.error(f"❌ Database setup error: {e}")
            raise
    
    def _setup_cpx_surveys(self):
        """
        CPX Surveys Collection
        
        Stores synced CPX survey inventory.
        Each survey can be activated/deactivated in the pool independently.
        """
        try:
            coll = self.db['cpx_surveys']
            
            # Create collection if doesn't exist
            if 'cpx_surveys' not in self.db.list_collection_names():
                self.db.create_collection('cpx_surveys')
            
            # Create indexes
            # Primary index: survey_id as _id
            coll.create_index([('_id', ASCENDING)], unique=True)
            
            # Filter indexes
            coll.create_index([('last_updated', DESCENDING)], background=True)
            coll.create_index([('loi', ASCENDING)], background=True)
            coll.create_index([('payout', DESCENDING)], background=True)
            coll.create_index([('country', ASCENDING)], background=True)
            coll.create_index([('category', ASCENDING)], background=True)
            coll.create_index([('is_active_in_pool', ASCENDING)], background=True)
            
            # Compound indexes
            coll.create_index(
                [('country', ASCENDING), ('last_updated', DESCENDING)],
                background=True
            )
            coll.create_index(
                [('is_active_in_pool', ASCENDING), ('payout', DESCENDING)],
                background=True
            )
            
            # Text search index for title/category
            coll.create_index([('title', TEXT), ('category', TEXT)], background=True)
            
            logger.info("✅ cpx_surveys collection ready")
            
            # Sample document schema
            """
            {
                "_id": "12345",                           // survey_id from CPX
                "title": "Consumer Opinion Survey",
                "loi": 10,                                // Length of interview (minutes)
                "payout": 2.50,                           // USD payout
                "category": "Health",
                "href": "https://click.cpx-research.com/?k=aB3fD...",
                "href_new": "https://click.cpx-research.com/?k=xyz...",
                "conversion_rate": 75,                    // Success rate %
                "country": "ALL",
                "provider": "CPX",
                "created_at": ISODate("2026-02-03T..."),
                "last_updated": ISODate("2026-02-03T..."),
                "click_count": 0,
                "last_clicked_at": null,
                "is_active_in_pool": false,
                "raw_data": { ... }                       // Full CPX response
            }
            """
            
        except Exception as e:
            logger.error(f"Setup cpx_surveys error: {e}")
    
    def _setup_url_parameters(self):
        """
        Traffic Records Collection (url_parameters)
        
        Stores traffic records (SFWID) linking respondent to survey to vendor.
        _id field is the SFWID (Survey Field Work ID).
        """
        try:
            coll = self.db['url_parameters']
            
            if 'url_parameters' not in self.db.list_collection_names():
                self.db.create_collection('url_parameters')
            
            # Create indexes
            # Primary index: _id (SFWID)
            coll.create_index([('_id', ASCENDING)], unique=True)
            
            # Lookup indexes
            coll.create_index([('vendorId', ASCENDING)], background=True)
            coll.create_index([('respondentId', ASCENDING)], background=True)
            coll.create_index([('cpxSurveyId', ASCENDING)], background=True)
            
            # Status indexes
            coll.create_index([('status', ASCENDING)], background=True)
            coll.create_index([('cpxPostbackReceived', ASCENDING)], background=True)
            
            # Timestamp indexes
            coll.create_index([('createdAt', DESCENDING)], background=True)
            coll.create_index([('cpxPostbackAt', DESCENDING)], background=True)
            
            # Compound indexes
            coll.create_index(
                [('vendorId', ASCENDING), ('createdAt', DESCENDING)],
                background=True
            )
            coll.create_index(
                [('status', ASCENDING), ('cpxPostbackReceived', ASCENDING)],
                background=True
            )
            
            logger.info("✅ url_parameters collection ready")
            
            # Sample document schema
            """
            {
                "_id": ObjectId("67890abcdef..."),        // SFWID
                "vendorId": "VEN_001",
                "countryCode": "US",
                "respondentId": "RESP_999",
                "clientIp": "103.21.124.1",
                "ipSource": "CF-Connecting-IP",
                "deviceFingerprint": "fp_a3f2b8d91c7e5...",
                "fingerprintSource": "client",
                "fingerprintComponents": { ... },
                "status": "INCOMPLETE",                  // INCOMPLETE, COMPLETE, FRAUD
                "createdAt": ISODate("2026-02-03T..."),
                "cpxSurveyId": "12345",
                "entryLink": "https://click.cpx-research.com/...",
                "surveyAssignedAt": ISODate("2026-02-03T..."),
                "cpxPostbackReceived": false,
                "cpxPostbackAt": null,
                "cpxPostbackStatus": null,              // 1=complete, 2=fraud
                "cpxTransId": null,                    // CPX transaction ID
                "vendorPostbackUrl": null,
                "vendorPostbackSuccess": null,
                "vendorPostbackStatus": null,
                "completedAt": null
            }
            """
            
        except Exception as e:
            logger.error(f"Setup url_parameters error: {e}")
    
    def _setup_survey_transactions(self):
        """
        Survey Transactions Collection
        
        Records transaction postbacks from CPX.
        trans_id is the PRIMARY identifier (single source of truth).
        """
        try:
            coll = self.db['survey_transactions']
            
            if 'survey_transactions' not in self.db.list_collection_names():
                self.db.create_collection('survey_transactions')
            
            # Create indexes
            # Primary index: trans_id
            coll.create_index([('trans_id', ASCENDING)], unique=True)
            
            # Lookup indexes
            coll.create_index([('subid', ASCENDING)], background=True)  # SFWID lookup
            coll.create_index([('survey_id', ASCENDING)], background=True)
            coll.create_index([('user_id', ASCENDING)], background=True)
            
            # Status indexes
            coll.create_index([('status', ASCENDING)], background=True)
            coll.create_index([('cpx_status', ASCENDING)], background=True)
            
            # Timestamp indexes
            coll.create_index([('created_at', DESCENDING)], background=True)
            coll.create_index([('completed_at', DESCENDING)], background=True)
            coll.create_index([('last_postback_at', DESCENDING)], background=True)
            
            # Compound indexes
            coll.create_index(
                [('status', ASCENDING), ('completed_at', DESCENDING)],
                background=True
            )
            coll.create_index(
                [('survey_id', ASCENDING), ('created_at', DESCENDING)],
                background=True
            )
            
            # TTL index: Auto-delete old pending transactions after 7 days
            coll.create_index(
                [('created_at', ASCENDING)],
                expireAfterSeconds=604800,  # 7 days
                partialFilterExpression={'status': 'pending'},
                background=True
            )
            
            logger.info("✅ survey_transactions collection ready")
            
            # Sample document schema
            """
            {
                "_id": ObjectId(...),
                "trans_id": "CPX_TRANS_123456",         // PRIMARY KEY
                "cpx_status": 1,                        // 1=complete, 2=fraud
                "status": "completed",                  // completed, fraud, canceled, pending
                "amount_usd": 2.50,
                "amount_local": 200.00,
                "subid": "SFWID_67890",                 // Links to traffic record
                "subid_2": null,
                "survey_id": "12345",                   // CPX offer_id
                "user_id": "USER_123",
                "vendor_id": "VEN_001",
                "country_code": "IN",
                "ip_address": "192.168.1.1",
                "callback_url": "https://...",
                "created_at": ISODate("2026-02-03T..."),
                "updated_at": ISODate("2026-02-03T..."),
                "last_postback_at": ISODate("2026-02-03T..."),
                "completed_at": ISODate("2026-02-03T..."),
                "postback_count": 1,
                "postback_hash": "f3a2b...",            // For deduplication
                "last_postback_hash": "..."
            }
            """
            
        except Exception as e:
            logger.error(f"Setup survey_transactions error: {e}")
    
    def _setup_cpx_postback_logs(self):
        """
        CPX Postback Logs Collection
        
        Logs all postback events for monitoring and debugging.
        Enables audit trail and performance analysis.
        """
        try:
            coll = self.db['cpx_postback_logs']
            
            if 'cpx_postback_logs' not in self.db.list_collection_names():
                self.db.create_collection('cpx_postback_logs')
            
            # Create indexes
            coll.create_index([('trans_id', ASCENDING)], background=True)
            coll.create_index([('timestamp', DESCENDING)], background=True)
            coll.create_index([('success', ASCENDING)], background=True)
            
            # Compound indexes
            coll.create_index(
                [('success', ASCENDING), ('timestamp', DESCENDING)],
                background=True
            )
            
            # TTL index: Auto-delete logs older than 30 days
            coll.create_index(
                [('timestamp', ASCENDING)],
                expireAfterSeconds=2592000,  # 30 days
                background=True
            )
            
            logger.info("✅ cpx_postback_logs collection ready")
            
            # Sample document schema
            """
            {
                "_id": ObjectId(...),
                "trans_id": "CPX_TRANS_123456",
                "cpx_status": 1,
                "amount_usd": 2.50,
                "subid": "SFWID_67890",
                "success": true,
                "message": "Processed",
                "timestamp": ISODate("2026-02-03T..."),
                "vendor_postback": {
                    "url": "https://vendor.com/complete?...",
                    "success": true,
                    "response_status": 200,
                    "error": null,
                    "respondent_id": "RESP_999",
                    "vendor_id": "VEN_001"
                }
            }
            """
            
        except Exception as e:
            logger.error(f"Setup cpx_postback_logs error: {e}")
    
    def _setup_cpx_filter_settings(self):
        """
        CPX Filter Settings Collection
        
        Stores filter preferences for survey allocation:
        - max_loi: Maximum length of interview
        - min_cpi: Minimum cost per interview (payout)
        - min_ir: Minimum incidence rate (conversion_rate)
        """
        try:
            coll = self.db['cpx_filter_settings']
            
            if 'cpx_filter_settings' not in self.db.list_collection_names():
                self.db.create_collection('cpx_filter_settings')
            
            # Create indexes
            coll.create_index([('vendor_id', ASCENDING)], unique=True, sparse=True)
            coll.create_index([('updated_at', DESCENDING)], background=True)
            
            logger.info("✅ cpx_filter_settings collection ready")
            
            # Sample document schema
            """
            {
                "_id": ObjectId(...),
                "name": "default",                   // or vendor_id for vendor-specific
                "vendor_id": "VEN_001",             // Optional, for vendor overrides
                "max_loi": 20,                      // Max minutes
                "min_cpi": 1.0,                     // Min USD payout
                "min_ir": 0,                        // Min conversion rate %
                "exclude_categories": ["Adult"],
                "include_countries": ["US", "UK"],
                "exclude_survey_ids": ["123"],
                "created_at": ISODate("2026-02-03T..."),
                "updated_at": ISODate("2026-02-03T..."),
                "created_by": "admin@..."
            }
            """
            
        except Exception as e:
            logger.error(f"Setup cpx_filter_settings error: {e}")


def setup_cpx_database(db):
    """Run CPX database setup"""
    setup = CPXDatabaseSetup(db)
    setup.setup_collections()
