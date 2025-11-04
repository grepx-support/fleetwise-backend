"""
SQLite Database Manager - Handles all SQLite-specific database operations.
"""
import sqlite3
import os
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

        # Get database path from parameter, environment variable, or default
        if db_path is None:
            db_path = os.environ.get('DB_PATH')

            # Fallback to default location
            if db_path is None:
                # fatal error if no path is provided
                raise Exception("DB_PATH environment variable not set and no db_path provided.")

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
        Get a direct SQLite database connection.
        
        Returns:
            sqlite3.Connection: A connection to the SQLite database
        """
        # SQLite connections are not thread-safe, so each call creates a new connection
        return sqlite3.connect(self.db_path)

    def get_db_type(self) -> str:
        """Get the database type identifier"""
        return 'sqlite'

    def get_db_path(self) -> str:
        """Get the database path being used"""
        return self.db_path
