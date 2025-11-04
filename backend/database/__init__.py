"""
Database Manager Package - Centralized database management.

This package provides a singleton factory pattern for database connections.
All database decisions are controlled through DBManager.

Usage:
    from backend.database import DBManager
    
    # Get SQLAlchemy URI for Flask
    uri = DBManager.get_sqlalchemy_uri()
    
    # Get direct connection (SQLite only)
    conn = DBManager.connect()
"""
from threading import Lock
import os
from .sqlite_db import SqliteDB
from .postgresql_db import PostgreSQLDB


class DBManager:
    """
    Singleton database manager - Factory and facade pattern.
    Single source of truth for ALL database decisions.

    Automatically selects the appropriate database implementation based on:
    - DB_TYPE environment variable (defaults to 'sqlite')

    Thread-safe singleton implemented using __new__ pattern with double-checked locking.

    Usage:
        # Get SQLAlchemy URI
        uri = DBManager.get_sqlalchemy_uri()

        # Get direct connection (SQLite only)
        conn = DBManager.connect()

        # Check database type
        if DBManager().is_sqlite():
            path = DBManager().get_db_path()
    """

    _instance = None
    _lock = Lock()
    _initialized = False

    def __new__(cls):
        """Create or return the singleton instance with thread-safe double-checked locking."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DBManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize DBManager with appropriate database implementation."""
        # Only initialize once
        if DBManager._initialized:
            return

        # Determine database type from environment
        db_type = os.environ.get('DB_TYPE', 'sqlite').lower()

        # Factory pattern: create appropriate database implementation
        if db_type == 'postgresql':
            self._db_impl = PostgreSQLDB()
        else:  # SQLite (default)
            self._db_impl = SqliteDB()

        DBManager._initialized = True
    
    @classmethod
    def get_sqlalchemy_uri(cls) -> str:
        """
        Get SQLAlchemy database URI for Flask-SQLAlchemy configuration.
        This is the single source of truth for SQLAlchemy connections.

        Returns:
            str: SQLAlchemy database URI
        """
        instance = cls()
        return instance._db_impl.get_sqlalchemy_uri()

    @classmethod
    def connect(cls):
        """
        Get a direct database connection instance.
        For SQLite: returns sqlite3.Connection
        For PostgreSQL: raises NotImplementedError (use SQLAlchemy instead)

        Returns:
            Connection object (type depends on database implementation)

        Raises:
            NotImplementedError: If using PostgreSQL (use SQLAlchemy instead)
        """
        instance = cls()
        return instance._db_impl.connect()
    
    def get_db_type(self) -> str:
        """Get the database type ('sqlite' or 'postgresql')"""
        if not hasattr(self, '_initialized'):
            self.__init__()
        return self._db_impl.get_db_type()
    
    def is_sqlite(self) -> bool:
        """Check if using SQLite database"""
        return self.get_db_type() == 'sqlite'
    
    def is_postgresql(self) -> bool:
        """Check if using PostgreSQL database"""
        return self.get_db_type() == 'postgresql'
    
    def get_db_path(self) -> str:
        """
        Get the database path being used (SQLite only)
        
        Returns:
            str: Database path (SQLite only)
            
        Raises:
            AttributeError: If called on PostgreSQL database
        """
        if not hasattr(self, '_initialized'):
            self.__init__()
        
        if self.is_sqlite():
            return self._db_impl.get_db_path()
        else:
            raise AttributeError("get_db_path() is only available for SQLite databases")

