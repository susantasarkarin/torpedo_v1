"""
MongoDB Connection Pool Manager
Separate pools for different workloads to prevent blocking
"""

import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from threading import Lock
import logging

logger = logging.getLogger(__name__)

assert os.getenv("MONGO_URI"), "MONGO_URI not set — refusing to start"

class MongoDBPoolManager:
    """
    Manages separate MongoDB connection pools for different workloads.
    This prevents email sync operations from blocking API responses.
    """
    
    _instance = None
    _lock = Lock()
    
    # Pool configurations
    POOL_CONFIGS = {
        'api': {
            'maxPoolSize': 20,
            'minPoolSize': 5,
            'maxIdleTimeMS': 30000,
            'waitQueueTimeoutMS': 5000,
            'serverSelectionTimeoutMS': 5000,
            'connectTimeoutMS': 5000,
        },
        'background': {
            'maxPoolSize': 10,
            'minPoolSize': 2,
            'maxIdleTimeMS': 60000,
            'waitQueueTimeoutMS': 30000,
            'serverSelectionTimeoutMS': 10000,
            'connectTimeoutMS': 10000,
        },
        'ai': {
            'maxPoolSize': 5,
            'minPoolSize': 1,
            'maxIdleTimeMS': 120000,
            'waitQueueTimeoutMS': 60000,
            'serverSelectionTimeoutMS': 30000,
            'connectTimeoutMS': 30000,
        }
    }
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._pools = {}
        self._mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
        self._db_name = os.getenv('MONGODB_DATABASE', 'campaign_platform')
        self._initialized = True
        
        logger.info("MongoDB Pool Manager initialized")
    
    def _create_client(self, pool_name: str) -> MongoClient:
        """Create a new MongoDB client with pool-specific configuration."""
        config = self.POOL_CONFIGS.get(pool_name, self.POOL_CONFIGS['api'])
        
        client = MongoClient(
            self._mongo_uri,
            **config,
            appName=f"campaign_platform_{pool_name}"
        )
        
        # Verify connection
        try:
            client.admin.command('ping')
            logger.info(f"MongoDB pool '{pool_name}' connected successfully")
        except ConnectionFailure as e:
            logger.error(f"Failed to connect MongoDB pool '{pool_name}': {e}")
            raise
        
        return client
    
    def get_client(self, pool_name: str = 'api') -> MongoClient:
        """Get a MongoDB client from the specified pool."""
        if pool_name not in self._pools:
            with self._lock:
                if pool_name not in self._pools:
                    self._pools[pool_name] = self._create_client(pool_name)
        
        return self._pools[pool_name]
    
    def get_db(self, pool_name: str = 'api'):
        """Get the database instance from the specified pool."""
        client = self.get_client(pool_name)
        return client[self._db_name]
    
    def get_collection(self, collection_name: str, pool_name: str = 'api'):
        """Get a collection from the specified pool."""
        db = self.get_db(pool_name)
        return db[collection_name]
    
    def close_all(self):
        """Close all connection pools."""
        with self._lock:
            for pool_name, client in self._pools.items():
                try:
                    client.close()
                    logger.info(f"Closed MongoDB pool '{pool_name}'")
                except Exception as e:
                    logger.error(f"Error closing pool '{pool_name}': {e}")
            self._pools.clear()
    
    def get_pool_stats(self) -> dict:
        """Get statistics for all pools."""
        stats = {}
        for pool_name, client in self._pools.items():
            try:
                server_info = client.server_info()
                stats[pool_name] = {
                    'connected': True,
                    'version': server_info.get('version', 'unknown'),
                    'config': self.POOL_CONFIGS.get(pool_name, {})
                }
            except Exception as e:
                stats[pool_name] = {
                    'connected': False,
                    'error': str(e)
                }
        return stats


# Singleton instance
pool_manager = MongoDBPoolManager()


# Convenience functions
def get_api_db():
    """Get database for API operations (fast, short-lived queries)."""
    return pool_manager.get_db('api')


def get_background_db():
    """Get database for background tasks (email sync, bulk operations)."""
    return pool_manager.get_db('background')


def get_ai_db():
    """Get database for AI processing (long-running, fewer connections)."""
    return pool_manager.get_db('ai')


def get_api_collection(name: str):
    """Get collection for API operations."""
    return pool_manager.get_collection(name, 'api')


def get_background_collection(name: str):
    """Get collection for background tasks."""
    return pool_manager.get_collection(name, 'background')


def get_ai_collection(name: str):
    """Get collection for AI processing."""
    return pool_manager.get_collection(name, 'ai')

