import os
import sys
import time
import logging
from contextlib import contextmanager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Change to the project root directory
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.environ.get("PROJECT_ROOT", script_dir)
os.chdir(project_root)

# Add project root to Python path
sys.path.insert(0, project_root)

@contextmanager
def app_context_with_cleanup():
    """Context manager for Flask app context with proper cleanup."""
    from backend.server import app
    from backend.extensions import db
    
    ctx = app.app_context()
    ctx.push()
    
    try:
        yield app
    finally:
        try:
            # Remove session
            db.session.remove()
            logger.info("Database session cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up database session: {e}")
        
        # Pop app context
        ctx.pop()
        logger.info("App context popped")

def main():
    """Main function with timeout protection and proper error handling."""
    start_time = time.time()
    timeout_seconds = 300  # 5 minute timeout
    
    try:
        logger.info("Setting up Flask application context...")
        
        with app_context_with_cleanup():
            # Check for timeout
            if time.time() - start_time > timeout_seconds:
                logger.warning("Script timed out during app context setup")
                return
            
            # Import the scheduler service
            from backend.services.scheduler_service import scheduler_service
            
            print("Starting job monitoring scan...")
            logger.info("Starting job monitoring process")
            
            # Run the monitoring function with timeout check
            if time.time() - start_time > timeout_seconds:
                logger.warning("Script timed out before monitoring execution")
                return
                
            scheduler_service.monitor_overdue_jobs()
            
            print("✅ Job monitoring completed successfully!")
            print("You can now check your alerts API endpoint for results.")
            logger.info("Job monitoring completed successfully")
            
    except Exception as e:
        logger.error(f"Error occurred: {e}", exc_info=True)
        print(f"❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        duration = time.time() - start_time
        logger.info(f"Script completed in {duration:.2f} seconds")

if __name__ == "__main__":
    main()