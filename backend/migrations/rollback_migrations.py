"""
Rollback Migration Helper

Provides utilities for rolling back migrations:
- Rollback to specific migration
- Rollback all migrations
- Selective rollback of fields/indexes/collections

Usage:
    python rollback_migrations.py              # Rollback last migration
    python rollback_migrations.py --all        # Rollback all migrations
    python rollback_migrations.py --to 001     # Rollback to specific migration
"""

from pymongo import MongoClient
from datetime import datetime
import logging
import os
import sys
import importlib
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class MigrationRollback:
    """Handles rollback of database migrations"""
    
    def __init__(self, mongodb_uri=None, database_name=None):
        """Initialize rollback handler"""
        self.mongodb_uri = mongodb_uri or os.getenv(
            "MONGODB_URI",
            "mongodb://localhost:27017"
        )
        self.database_name = database_name or os.getenv(
            "MONGODB_DB",
            "email_automation"
        )
        self.client = MongoClient(self.mongodb_uri)
        self.db = self.client[self.database_name]
        self.migrations_dir = Path(__file__).parent
    
    def get_applied_migrations(self):
        """Get list of applied migrations in reverse chronological order"""
        result = self.db.migrations_log.find(
            {"status": "success"}
        ).sort("completed_at", -1)
        return [m["migration"] for m in result]
    
    def load_migration(self, migration_name):
        """Dynamically load a migration module"""
        try:
            spec = importlib.util.spec_from_file_location(
                migration_name,
                self.migrations_dir / f"{migration_name}.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.error(f"Failed to load migration {migration_name}: {str(e)}")
            raise
    
    def rollback_single(self, migration_name):
        """Rollback a single migration"""
        logger.info(f"Rolling back migration: {migration_name}")
        
        try:
            migration = self.load_migration(migration_name)
            
            if not hasattr(migration, 'down'):
                logger.error(f"Migration {migration_name} does not have down() function")
                return False
            
            logger.info(f"Running down() for {migration_name}")
            result = migration.down(self.db)
            
            if result:
                # Remove from migrations_log
                self.db.migrations_log.delete_one({"migration": migration_name})
                logger.info(f"✓ Rollback of {migration_name} completed")
                return True
            else:
                logger.error(f"✗ Rollback of {migration_name} failed: down() returned False")
                return False
                
        except Exception as e:
            logger.error(f"✗ Rollback of {migration_name} failed: {str(e)}")
            raise
    
    def rollback_last(self):
        """Rollback the most recently applied migration"""
        applied = self.get_applied_migrations()
        
        if not applied:
            logger.warning("No migrations to rollback")
            return False
        
        last_migration = applied[0]
        return self.rollback_single(last_migration)
    
    def rollback_all(self):
        """Rollback all applied migrations in reverse order"""
        logger.info("Rolling back all migrations")
        
        applied = self.get_applied_migrations()
        
        if not applied:
            logger.warning("No migrations to rollback")
            return True
        
        logger.info(f"Found {len(applied)} applied migration(s)")
        
        failed = 0
        
        for migration_name in applied:
            try:
                if not self.rollback_single(migration_name):
                    failed += 1
                    # Stop on first failure
                    break
            except Exception as e:
                failed += 1
                logger.error(f"Stopping rollback due to error: {str(e)}")
                break
        
        # Summary
        logger.info("=" * 60)
        logger.info(f"Rollback completed")
        logger.info(f"Failed: {failed}")
        logger.info("=" * 60)
        
        return failed == 0
    
    def rollback_to(self, target_migration):
        """Rollback to before a specific migration"""
        logger.info(f"Rolling back to before {target_migration}")
        
        applied = self.get_applied_migrations()
        
        # Find target migration
        if target_migration not in applied:
            logger.error(f"Migration {target_migration} not found in applied migrations")
            return False
        
        # Rollback everything after target (not including target)
        target_index = applied.index(target_migration)
        to_rollback = applied[:target_index]
        
        if not to_rollback:
            logger.info(f"Migration {target_migration} is already the earliest")
            return True
        
        logger.info(f"Rolling back {len(to_rollback)} migration(s)")
        
        failed = 0
        for migration_name in to_rollback:
            try:
                if not self.rollback_single(migration_name):
                    failed += 1
                    break
            except Exception as e:
                failed += 1
                logger.error(f"Stopping rollback due to error: {str(e)}")
                break
        
        return failed == 0
    
    def show_applied(self):
        """Show list of applied migrations"""
        logger.info("Applied Migrations")
        logger.info("=" * 60)
        
        applied = self.db.migrations_log.find(
            {"status": "success"}
        ).sort("completed_at", 1)
        
        count = 0
        for m in applied:
            timestamp = m.get("completed_at", "Unknown")
            logger.info(f"✓ {m['migration']} ({timestamp})")
            count += 1
        
        if count == 0:
            logger.info("No migrations applied")
        
        logger.info("=" * 60)
    
    def close(self):
        """Close database connection"""
        self.client.close()


def main():
    """Main entry point"""
    load_dotenv()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    rollback = MigrationRollback()
    
    try:
        if len(sys.argv) > 1:
            command = sys.argv[1]
            
            if command == "--all":
                success = rollback.rollback_all()
                return success
            elif command == "--to" and len(sys.argv) > 2:
                target = sys.argv[2]
                success = rollback.rollback_to(target)
                return success
            elif command == "--show":
                rollback.show_applied()
                return True
            else:
                logger.error(f"Unknown command: {command}")
                logger.info("Usage:")
                logger.info("  python rollback_migrations.py              # Rollback last")
                logger.info("  python rollback_migrations.py --all       # Rollback all")
                logger.info("  python rollback_migrations.py --to 001    # Rollback to migration")
                logger.info("  python rollback_migrations.py --show      # Show applied")
                return False
        else:
            # Rollback last migration
            success = rollback.rollback_last()
            return success
    finally:
        rollback.close()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
