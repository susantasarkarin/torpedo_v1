"""
Migration Runner

Orchestrates execution of all database migrations in order.
- Tracks completed migrations in migrations_log collection
- Skips already-run migrations
- Reports progress and handles errors
- Supports rolling back to previous states

Usage:
    python run_migrations.py              # Run all pending migrations
    python run_migrations.py --rollback   # Rollback last migration
    python run_migrations.py --status     # Check migration status
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


class MigrationRunner:
    """Orchestrates database migrations"""
    
    def __init__(self, MONGO_URI=None, database_name=None):
        """Initialize migration runner"""
        self.MONGO_URI = MONGO_URI or os.getenv(
            "MONGO_URI",
            "mongodb://localhost:27017"
        )
        self.database_name = database_name or os.getenv(
            "MONGODB_DB",
            "email_automation"
        )
        self.client = MongoClient(self.MONGO_URI)
        self.db = self.client[self.database_name]
        self.migrations_dir = Path(__file__).parent
        
        # Ensure migrations_log collection exists
        if "migrations_log" not in self.db.list_collection_names():
            self.db.create_collection("migrations_log")
    
    def get_migration_files(self):
        """Get list of migration files in order"""
        migration_files = []
        for file in sorted(self.migrations_dir.glob("*.py")):
            name = file.stem
            # Skip this file, __init__, and rollback script
            if name not in ["run_migrations", "rollback_migrations", "__init__"]:
                migration_files.append(name)
        return migration_files
    
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
    
    def is_migration_applied(self, migration_name):
        """Check if migration has been applied"""
        result = self.db.migrations_log.find_one({
            "migration": migration_name,
            "status": "success"
        })
        return result is not None
    
    def mark_migration_complete(self, migration_name, status="success", error=None):
        """Mark migration as complete in log"""
        self.db.migrations_log.update_one(
            {"migration": migration_name},
            {"$set": {
                "migration": migration_name,
                "status": status,
                "completed_at": datetime.utcnow(),
                "error": error
            }},
            upsert=True
        )
    
    def run_migration(self, migration_name):
        """Run a single migration"""
        logger.info(f"Processing migration: {migration_name}")
        
        # Check if already applied
        if self.is_migration_applied(migration_name):
            logger.info(f"Migration {migration_name} already applied, skipping")
            return True
        
        try:
            # Load and run migration
            migration = self.load_migration(migration_name)
            
            logger.info(f"Running up() for {migration_name}")
            result = migration.up(self.db)
            
            if result:
                self.mark_migration_complete(migration_name, "success")
                logger.info(f"âœ“ Migration {migration_name} completed successfully")
                return True
            else:
                self.mark_migration_complete(migration_name, "failed", "up() returned False")
                logger.error(f"âœ— Migration {migration_name} failed: up() returned False")
                return False
                
        except Exception as e:
            error_msg = str(e)
            self.mark_migration_complete(migration_name, "failed", error_msg)
            logger.error(f"âœ— Migration {migration_name} failed: {error_msg}")
            raise
    
    def run_all(self):
        """Run all pending migrations in order"""
        logger.info("Starting migration run")
        logger.info(f"Database: {self.database_name}")
        
        migration_files = self.get_migration_files()
        
        if not migration_files:
            logger.warning("No migrations found")
            return True
        
        logger.info(f"Found {len(migration_files)} migration(s)")
        
        successful = 0
        failed = 0
        
        for migration_name in migration_files:
            try:
                if self.run_migration(migration_name):
                    successful += 1
                else:
                    failed += 1
                    # Stop on first failure
                    break
            except Exception as e:
                failed += 1
                logger.error(f"Stopping migration run due to error: {str(e)}")
                break
        
        # Summary
        logger.info("=" * 60)
        logger.info(f"Migration run completed")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info("=" * 60)
        
        return failed == 0
    
    def rollback_last(self):
        """Rollback the last applied migration"""
        logger.info("Starting rollback")
        
        # Get migrations in reverse order
        migration_files = sorted(self.get_migration_files(), reverse=True)
        
        for migration_name in migration_files:
            result = self.db.migrations_log.find_one({
                "migration": migration_name,
                "status": "success"
            })
            
            if result:
                logger.info(f"Rolling back: {migration_name}")
                
                try:
                    migration = self.load_migration(migration_name)
                    
                    if hasattr(migration, 'down'):
                        migration.down(self.db)
                        self.db.migrations_log.delete_one({
                            "migration": migration_name
                        })
                        logger.info(f"âœ“ Rollback of {migration_name} completed")
                        return True
                    else:
                        logger.error(f"Migration {migration_name} does not have down() function")
                        return False
                        
                except Exception as e:
                    logger.error(f"Rollback failed: {str(e)}")
                    return False
        
        logger.warning("No migrations to rollback")
        return False
    
    def show_status(self):
        """Show status of all migrations"""
        logger.info("Migration Status")
        logger.info("=" * 60)
        
        migration_files = self.get_migration_files()
        applied = self.db.migrations_log.find({"status": "success"})
        applied_names = {m["migration"] for m in applied}
        
        for migration_name in migration_files:
            status = "âœ“ APPLIED" if migration_name in applied_names else "âŠ˜ PENDING"
            logger.info(f"{status}  {migration_name}")
        
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
    
    runner = MigrationRunner()
    
    try:
        if len(sys.argv) > 1:
            command = sys.argv[1]
            
            if command == "--rollback":
                runner.rollback_last()
            elif command == "--status":
                runner.show_status()
            else:
                logger.error(f"Unknown command: {command}")
                logger.info("Usage: python run_migrations.py [--rollback|--status]")
                return False
        else:
            # Run all migrations
            success = runner.run_all()
            return success
    finally:
        runner.close()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

