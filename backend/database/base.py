"""
Base Database Manager class - Abstract base class for all database implementations.
"""
from abc import ABC, abstractmethod


class BaseDBManager(ABC):
    """
    Abstract base class for database managers.
    All database implementations (SQLite, PostgreSQL, etc.) should inherit from this.
    """
    
    def __init__(self):
        """Initialize the database manager"""
        self._initialized = True
    
    @abstractmethod
    def get_sqlalchemy_uri(self) -> str:
        """
        Get SQLAlchemy database URI for Flask-SQLAlchemy configuration.
        
        Returns:
            str: SQLAlchemy database URI
        """
        pass
    
    @abstractmethod
    def connect(self):
        """
        Get a direct database connection instance.
        
        Returns:
            Connection object (type depends on database implementation)
            
        Raises:
            NotImplementedError: If direct connections are not supported
        """
        pass
    
    @abstractmethod
    def get_db_type(self) -> str:
        """
        Get the database type identifier.
        
        Returns:
            str: Database type (e.g., 'sqlite', 'postgresql')
        """
        pass
    
    def is_sqlite(self) -> bool:
        """Check if using SQLite database"""
        return self.get_db_type() == 'sqlite'
    
    def is_postgresql(self) -> bool:
        """Check if using PostgreSQL database"""
        return self.get_db_type() == 'postgresql'

