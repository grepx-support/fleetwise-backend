import logging
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from typing import Dict, Any

logger = logging.getLogger(__name__)

class MonitoredSQLAlchemy(SQLAlchemy):
    """Extended SQLAlchemy with connection pool monitoring."""
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """Get current connection pool statistics."""
        try:
            if hasattr(self.engine, 'pool'):
                pool = self.engine.pool
                return {
                    'pool_size': pool.size() if hasattr(pool, 'size') else 0,
                    'checked_out': pool.checkedout() if hasattr(pool, 'checkedout') else 0,
                    'overflow': getattr(pool, 'overflow', 0),
                    'utilization_percent': (
                        (pool.checkedout() / max(pool.size(), 1)) * 100 
                        if hasattr(pool, 'checkedout') and hasattr(pool, 'size') 
                        else 0
                    )
                }
            else:
                return {
                    'pool_size': 0,
                    'checked_out': 0,
                    'overflow': 0,
                    'utilization_percent': 0
                }
        except Exception as e:
            logger.error(f"Error getting pool stats: {e}")
            return {
                'pool_size': 0,
                'checked_out': 0,
                'overflow': 0,
                'utilization_percent': 0,
                'error': str(e)
            }
    
    def health_check(self) -> bool:
        """Perform a health check on the database connection."""
        try:
            # Execute a simple query to test connectivity
            result = self.session.execute("SELECT 1").scalar()
            return result == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

db = MonitoredSQLAlchemy()
mail = Mail()