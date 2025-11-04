"""
PostgreSQL Database Manager - Handles all PostgreSQL-specific database operations.
"""
import os
from urllib.parse import quote_plus
from .base import BaseDBManager


class PostgreSQLDB(BaseDBManager):
    """
    PostgreSQL database manager implementation.
    Handles PostgreSQL-specific configuration and connections.
    """
    
    def __init__(self):
        """Initialize PostgreSQL database manager from environment variables."""
        super().__init__()

        # PostgreSQL configuration from environment variables
        self.db_host = os.environ.get('DB_HOST', 'localhost')
        self.db_port = os.environ.get('DB_PORT', '5432')
        self.db_name = os.environ.get('DB_NAME', 'fleetwise')
        self.db_user = os.environ.get('DB_USER', 'postgres')
        self.db_password = os.environ.get('DB_PASSWORD', '')

        # Build PostgreSQL connection string with password using name mangling for security
        password_escaped = quote_plus(self.db_password) if self.db_password else ''
        # Use name mangling (__) to make the URI with plaintext password private
        self.__sqlalchemy_uri = (
            f"postgresql://{self.db_user}:{password_escaped}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )

        # Create a sanitized URI for logging (replaces password with ***)
        self._log_safe_uri = (
            f"postgresql://{self.db_user}:***@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )

        print(f"PostgreSQLDB initialized: {self._log_safe_uri}")
    
    def get_sqlalchemy_uri(self) -> str:
        """
        Get SQLAlchemy database URI for PostgreSQL.

        Returns:
            str: SQLAlchemy database URI (postgresql://user:pass@host:port/dbname)

        Security Note: This returns the URI with plaintext password. Ensure this
        URI is never logged, serialized, or inspected in debugging contexts where
        it could leak credentials. Use _log_safe_uri for logging instead.
        """
        return self.__sqlalchemy_uri
    
    def connect(self):
        """
        Get a direct PostgreSQL database connection.
        
        Returns:
            NotImplementedError: Direct PostgreSQL connections are not supported.
                                Use SQLAlchemy for PostgreSQL connections.
        
        Raises:
            NotImplementedError: Always raises (use SQLAlchemy instead)
        """
        raise NotImplementedError(
            "Direct PostgreSQL connections are not supported. "
            "Please use SQLAlchemy for PostgreSQL connections."
        )
    
    def get_db_type(self) -> str:
        """Get the database type identifier"""
        return 'postgresql'
    
    def get_db_host(self) -> str:
        """Get the PostgreSQL host"""
        return self.db_host
    
    def get_db_port(self) -> str:
        """Get the PostgreSQL port"""
        return self.db_port
    
    def get_db_name(self) -> str:
        """Get the PostgreSQL database name"""
        return self.db_name

