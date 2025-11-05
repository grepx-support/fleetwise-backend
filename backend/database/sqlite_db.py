"""
SQLite Database Manager - Handles all SQLite-specific database operations.
"""
import sqlite3
import os
from pathlib import Path
from .base import BaseDBManager


class SqliteDB(BaseDBManager):
    """
    SQLite database manager implementation.
    Handles SQLite-specific configuration and connections.
    """

    def __init__(self, db_path=None):
        """
        Initialize SQLite database manager.
        
        Args:
            db_path: Optional database path. 
                     If None, uses DB_PATH environment variable or default location.
        """
        super().__init__()

        # Get database path from parameter, environment variable, or fallback default
        if db_path is None:
            db_path = os.environ.get('DB_PATH')

        # Fallback to default location if not provided
        if db_path is None:
            # Use same default as config.py for consistency
            # Path: backend/database/sqlite_db.py -> repos/fleetwise-storage/database
            fallback_path = Path(__file__).resolve().parents[3] / "fleetwise-storage" / "database" / "fleetwise.db"
            db_path = str(fallback_path)
            print(f"WARNING: DB_PATH not set, using fallback default: {db_path}")

        self.db_path = db_path

        # Ensure the directory exists for the database file
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            print(f"Created database directory: {db_dir}")

        self.sqlalchemy_uri = f"sqlite:///{self.db_path}"

        print(f"SqliteDB initialized with database: {self.db_path}")

    def get_sqlalchemy_uri(self) -> str:
        """
        Get SQLAlchemy database URI for SQLite.
        
        Returns:
            str: SQLAlchemy database URI (sqlite:///path/to/database.db)
        """
        return self.sqlalchemy_uri

    def connect(self):
        """
        Get a direct SQLite database connection configured for thread safety.

        Returns:
            sqlite3.Connection: A connection to the SQLite database with threading support

        Note: Configured for multi-threaded environments with proper isolation and timeout.
        """
        # Configure connection for thread safety and multi-threaded access
        # check_same_thread=False allows use across threads (required for Flask)
        # timeout=30 prevents indefinite blocking under write contention
        # isolation_level='DEFERRED' allows better concurrency
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level='DEFERRED'
        )
        # Use Row factory for dict-like access to query results
        conn.row_factory = sqlite3.Row
        return conn

    def get_db_type(self) -> str:
        """Get the database type identifier"""
        return 'sqlite'

    def get_db_path(self) -> str:
        """Get the database path being used"""
        return self.db_path
