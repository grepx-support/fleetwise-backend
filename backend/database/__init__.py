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


def singleton(cls):
    """Thread-safe singleton decorator"""
    instance = None
    lock = Lock()
    
    def get_instance(*args, **kwargs):
        nonlocal instance
        if instance is None:
            with lock:
                if instance is None:
                    instance = cls(*args, **kwargs)
        return instance
    
    # Preserve class methods and attributes by copying them
    for attr_name in dir(cls):
        if not attr_name.startswith('__') or attr_name in ['__name__', '__doc__', '__module__']:
            attr = getattr(cls, attr_name)
            # Copy methods and class attributes
            if callable(attr) or not callable(getattr(type(attr), '__get__', None)):
                setattr(get_instance, attr_name, attr)
    
    get_instance._class = cls
    get_instance.__name__ = cls.__name__
    get_instance.__doc__ = cls.__doc__
    get_instance.__module__ = cls.__module__
    
    return get_instance


@singleton
class DBManager:
    """
    Singleton database manager - Factory and facade pattern.
    Single source of truth for ALL database decisions.
    
    Automatically selects the appropriate database implementation based on:
    - DB_TYPE environment variable (defaults to 'sqlite')
    
    Usage:
        # Get SQLAlchemy URI
        uri = DBManager.get_sqlalchemy_uri()
        
        # Get direct connection (SQLite only)
        conn = DBManager.connect()
        
        # Check database type
        if DBManager().is_sqlite():
            path = DBManager().get_db_path()
    """
    
    def __init__(self):
        """Initialize DBManager with appropriate database implementation"""
        if not hasattr(self, '_initialized'):
            # Determine database type from environment
            db_type = os.environ.get('DB_TYPE', 'sqlite').lower()
            
            # Factory pattern: create appropriate database implementation
            if db_type == 'postgresql':
                self._db_impl = PostgreSQLDB()
            else:  # SQLite (default)
                self._db_impl = SqliteDB()
            
            self._initialized = True
    
    @staticmethod
    def get_sqlalchemy_uri() -> str:
        """
        Get SQLAlchemy database URI for Flask-SQLAlchemy configuration.
        This is the single source of truth for SQLAlchemy connections.
        
        Returns:
            str: SQLAlchemy database URI
        """
        manager = DBManager()
        return manager._db_impl.get_sqlalchemy_uri()
    
    @staticmethod
    def connect():
        """
        Get a direct database connection instance.
        For SQLite: returns sqlite3.Connection
        For PostgreSQL: raises NotImplementedError (use SQLAlchemy instead)
        
        Returns:
            Connection object (type depends on database implementation)
            
        Raises:
            NotImplementedError: If using PostgreSQL (use SQLAlchemy instead)
        """
        manager = DBManager()
        return manager._db_impl.connect()
    
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

