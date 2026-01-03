"""
CENTRALIZED DATABASE MODULE
Singleton pattern for MongoDB connections to avoid multiple clients.

Usage:
    from database import get_database, get_collection
    
    db = get_database("email_automation")
    collection = get_collection("email_automation", "contacts")
"""

import os
from typing import Optional, Dict
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection
from dotenv import load_dotenv
import threading

load_dotenv()


class DatabaseManager:
    """
    Singleton MongoDB connection manager.
    Provides a single MongoClient instance for the entire application.
    """
    
    _instance: Optional['DatabaseManager'] = None
    _lock: threading.Lock = threading.Lock()
    _client: Optional[MongoClient] = None
    _databases: Dict[str, Database] = {}
    
    def __new__(cls) -> 'DatabaseManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the MongoDB client with connection settings."""
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        
        try:
            self._client = MongoClient(
                mongo_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=30000,
                maxPoolSize=50,
                minPoolSize=5,
                retryWrites=True
            )
            # Test connection
            self._client.admin.command('ping')
            print("✅ MongoDB singleton client initialized successfully")
        except Exception as e:
            print(f"❌ MongoDB connection failed: {e}")
            raise
    
    @property
    def client(self) -> MongoClient:
        """Get the MongoDB client instance."""
        if self._client is None:
            self._initialize_client()
        return self._client
    
    def get_database(self, db_name: str) -> Database:
        """
        Get a database instance. Caches database references.
        
        Args:
            db_name: Name of the database
            
        Returns:
            MongoDB Database instance
        """
        if db_name not in self._databases:
            self._databases[db_name] = self.client[db_name]
        return self._databases[db_name]
    
    def get_collection(self, db_name: str, collection_name: str) -> Collection:
        """
        Get a collection instance.
        
        Args:
            db_name: Name of the database
            collection_name: Name of the collection
            
        Returns:
            MongoDB Collection instance
        """
        db = self.get_database(db_name)
        return db[collection_name]
    
    def close(self):
        """Close the MongoDB client connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._databases = {}
            print("✅ MongoDB client connection closed")


# ============== CONVENIENCE FUNCTIONS ==============

_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get the singleton database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_client() -> MongoClient:
    """Get the MongoDB client instance."""
    return get_db_manager().client


def get_database(db_name: str) -> Database:
    """
    Get a database instance.
    
    Args:
        db_name: Name of the database
        
    Returns:
        MongoDB Database instance
    """
    return get_db_manager().get_database(db_name)


def get_collection(db_name: str, collection_name: str) -> Collection:
    """
    Get a collection instance.
    
    Args:
        db_name: Name of the database
        collection_name: Name of the collection
        
    Returns:
        MongoDB Collection instance
    """
    return get_db_manager().get_collection(db_name, collection_name)


# ============== DATABASE CONSTANTS ==============

# Database names
DB_EMAIL_AUTOMATION = "email_automation"
DB_FINANCE = "finance_db"
DB_TRAFFIC = "traffic_flow_db"
DB_CPX = "cpx_research"
DB_SETTINGS = "torpedo_settings"

# Collection names - Email Automation
COL_CONTACTS = "contacts"
COL_LISTS = "lists"
COL_TEMPLATES = "templates"
COL_REPORTS = "reports"
COL_PROJECTS = "projects"
COL_VENDORS = "vendors"
COL_USERS = "users"
COL_LEADS = "leads"
COL_WEB_SEARCH_JOBS = "web_search_jobs"
COL_OPENAI_USAGE = "openai_usage_logs"

# Collection names - Finance
COL_INVOICES = "invoices"
COL_CUSTOMERS = "customers"
COL_BILLING_VENDORS = "billing_vendors"

# Collection names - Traffic
COL_URL_PARAMETERS = "url_parameters"
COL_CPX_CALLBACK_LOGS = "cpx_callback_logs"

# Collection names - CPX
COL_CPX_SURVEYS = "cpx_surveys"
COL_CPX_FILTERS = "cpx_filters"

# Collection names - Settings
COL_APP_SETTINGS = "app_settings"
COL_SURVEY_FILTERS = "survey_filters"

# Collection names - Operations
COL_PANEL_VENDORS = "panel_vendors"
COL_CLIENTS = "clients"


# ============== PRE-CONFIGURED COLLECTIONS ==============

def get_email_automation_db() -> Database:
    """Get the email_automation database."""
    return get_database(DB_EMAIL_AUTOMATION)


def get_finance_db() -> Database:
    """Get the finance database."""
    return get_database(DB_FINANCE)


def get_traffic_db() -> Database:
    """Get the traffic flow database."""
    return get_database(DB_TRAFFIC)


def get_cpx_db() -> Database:
    """Get the CPX research database."""
    return get_database(DB_CPX)


def get_settings_db() -> Database:
    """Get the settings database."""
    return get_database(DB_SETTINGS)


# ============== COMMONLY USED COLLECTIONS ==============

def get_contacts_collection() -> Collection:
    """Get the contacts collection."""
    return get_collection(DB_EMAIL_AUTOMATION, COL_CONTACTS)


def get_users_collection() -> Collection:
    """Get the users collection."""
    return get_collection(DB_EMAIL_AUTOMATION, COL_USERS)


def get_leads_collection() -> Collection:
    """Get the leads collection."""
    return get_collection(DB_EMAIL_AUTOMATION, COL_LEADS)


def get_invoices_collection() -> Collection:
    """Get the invoices collection."""
    return get_collection(DB_FINANCE, COL_INVOICES)


def get_customers_collection() -> Collection:
    """Get the customers collection."""
    return get_collection(DB_FINANCE, COL_CUSTOMERS)


def get_billing_vendors_collection() -> Collection:
    """Get the billing vendors collection."""
    return get_collection(DB_FINANCE, COL_BILLING_VENDORS)


def get_panel_vendors_collection() -> Collection:
    """Get the panel vendors collection (operations)."""
    return get_collection(DB_EMAIL_AUTOMATION, COL_PANEL_VENDORS)


def get_clients_collection() -> Collection:
    """Get the clients collection (operations)."""
    return get_collection(DB_EMAIL_AUTOMATION, COL_CLIENTS)


def get_app_settings_collection() -> Collection:
    """Get the app settings collection."""
    return get_collection(DB_SETTINGS, COL_APP_SETTINGS)


def get_cpx_surveys_collection() -> Collection:
    """Get the CPX surveys collection."""
    return get_collection(DB_CPX, COL_CPX_SURVEYS)


def get_url_parameters_collection() -> Collection:
    """Get the URL parameters collection (traffic)."""
    return get_collection(DB_TRAFFIC, COL_URL_PARAMETERS)
