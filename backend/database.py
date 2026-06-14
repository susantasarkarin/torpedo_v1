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
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from dotenv import load_dotenv
import threading
import asyncio

load_dotenv()

assert os.getenv("MONGO_URI"), "MONGO_URI not set — refusing to start"


class DatabaseManager:
    """
    Singleton MongoDB connection manager.
    Provides both synchronous and asynchronous client instances.
    """
    
    _instance: Optional['DatabaseManager'] = None
    _lock: threading.Lock = threading.Lock()
    _client: Optional[MongoClient] = None
    _async_client: Optional[AsyncIOMotorClient] = None
    _async_loop = None  # event loop the Motor client is currently bound to
    _databases: Dict[str, Database] = {}
    _async_databases: Dict[str, AsyncIOMotorDatabase] = {}
    
    def __new__(cls) -> 'DatabaseManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            self._initialize_client()
        # The async (Motor) client is created lazily, bound to the running
        # event loop, via _ensure_async_client(). Creating it eagerly here — at
        # the first DB touch, which is often a synchronous call (e.g. login) —
        # bound it to the wrong loop under uvloop, so every `await` on an async
        # collection hung forever while sync endpoints worked fine.
    
    def _initialize_client(self):
        """Initialize the synchronous MongoDB client."""
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        try:
            self._client = MongoClient(
                mongo_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=20000,
                maxPoolSize=30,
                minPoolSize=5,
                maxIdleTimeMS=45000,
                retryWrites=True,
                retryReads=True,
                compressors='zstd,snappy,zlib',
            )
            self._client.admin.command('ping')
            print("✅ MongoDB sync client initialized")
        except Exception as e:
            print(f"❌ MongoDB sync connection failed: {e}")
            raise

    def _initialize_async_client(self):
        """Initialize the asynchronous Motor client."""
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        try:
            self._async_client = AsyncIOMotorClient(
                mongo_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                maxPoolSize=50,
                minPoolSize=5,
                retryWrites=True,
                compressors='zstd,snappy,zlib',
            )
            print("✅ MongoDB async (Motor) client initialized")
        except Exception as e:
            print(f"❌ MongoDB async connection failed: {e}")
            raise

    def _ensure_async_client(self) -> AsyncIOMotorClient:
        """Return a Motor client bound to the currently-running event loop.

        Motor binds a client to the event loop running when it is created;
        operations scheduled from any other loop hang forever. uvicorn serves on
        uvloop, so we (re)create the client whenever the running loop differs
        from the one the cached client was bound to.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._async_client is None or self._async_loop is not loop:
            # Databases cached against the stale client/loop must be dropped too.
            self._async_databases = {}
            self._initialize_async_client()
            self._async_loop = loop
        return self._async_client

    @property
    def client(self) -> MongoClient:
        return self._client

    @property
    def async_client(self) -> AsyncIOMotorClient:
        return self._ensure_async_client()
    
    def get_database(self, db_name: str) -> Database:
        if db_name not in self._databases:
            self._databases[db_name] = self.client[db_name]
        return self._databases[db_name]

    def get_async_database(self, db_name: str) -> AsyncIOMotorDatabase:
        # Ensure the client matches the running loop FIRST — this may clear the
        # cached databases, so the membership check below must come after it.
        client = self._ensure_async_client()
        if db_name not in self._async_databases:
            self._async_databases[db_name] = client[db_name]
        return self._async_databases[db_name]
    
    def get_collection(self, db_name: str, collection_name: str) -> Collection:
        db = self.get_database(db_name)
        return db[collection_name]

    def get_async_collection(self, db_name: str, collection_name: str) -> AsyncIOMotorCollection:
        db = self.get_async_database(db_name)
        return db[collection_name]
    
    def close(self):
        """Close both clients."""
        if self._client:
            self._client.close()
            self._client = None
        if self._async_client:
            self._async_client.close()
            self._async_client = None
        self._databases = {}
        self._async_databases = {}
        print("✅ MongoDB connections closed")


# ============== CONVENIENCE FUNCTIONS ==============

_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get the singleton database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_client() -> MongoClient:
    """Get the MongoDB sync client instance."""
    return get_db_manager().client


def get_async_client() -> AsyncIOMotorClient:
    """Get the MongoDB async client instance."""
    return get_db_manager().async_client


def get_database(db_name: str) -> Database:
    """Get a synchronous database instance."""
    return get_db_manager().get_database(db_name)


def get_async_database(db_name: str) -> AsyncIOMotorDatabase:
    """Get an asynchronous database instance."""
    return get_db_manager().get_async_database(db_name)


def get_collection(db_name: str, collection_name: str) -> Collection:
    """Get a synchronous collection instance."""
    return get_db_manager().get_collection(db_name, collection_name)


def get_async_collection(db_name: str, collection_name: str) -> AsyncIOMotorCollection:
    """Get an asynchronous collection instance."""
    return get_db_manager().get_async_collection(db_name, collection_name)


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
    """Get the URL parameters collection (traffic flow db)."""
    return get_collection(DB_TRAFFIC, COL_URL_PARAMETERS)


def get_async_url_parameters_collection() -> AsyncIOMotorCollection:
    """Get the async URL parameters collection (traffic flow db)."""
    return get_async_collection(DB_TRAFFIC, COL_URL_PARAMETERS)


def get_async_cpx_callback_logs_collection() -> AsyncIOMotorCollection:
    """Get the async CPX callback logs collection (traffic flow db)."""
    return get_async_collection(DB_TRAFFIC, COL_CPX_CALLBACK_LOGS)


def get_async_vendors_collection() -> AsyncIOMotorCollection:
    """Get the async vendors collection (email automation db)."""
    return get_async_collection(DB_EMAIL_AUTOMATION, COL_VENDORS)


def get_db():
    """
    Get a DatabaseManager instance for use in routers.
    This is a convenience function for dependency injection.
    Returns the db_manager which provides access to all databases.
    """
    return get_db_manager()
