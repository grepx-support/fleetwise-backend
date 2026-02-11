import os
import sys
import time
import logging
from contextlib import contextmanager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    timeout_seconds = 60  # 1 minute timeout
    
    try:
        logger.info("=== Starting Job Statistics Analysis ===")
        
        with app_context_with_cleanup() as app:
            # Check for timeout
            if time.time() - start_time > timeout_seconds:
                logger.warning("Script timed out during app context setup")
                return
            
            from backend.models.job import Job
            from backend.models.contractor import Contractor
            from backend.models.bill import BillItem
            
            # Check for timeout periodically
            if time.time() - start_time > timeout_seconds:
                logger.warning("Script timed out before database queries")
                return
            
            print("=== Job Statistics ===")
            total_jobs = Job.query.count()
            print(f"Total jobs: {total_jobs}")
            
            # Check jobs by status
            statuses = Job.query.with_entities(Job.status).distinct().all()
            print("\nJobs by status:")
            for status in statuses:
                count = Job.query.filter_by(status=status[0]).count()
                print(f"  {status[0]}: {count}")
            
            # Check jobs with contractors
            jobs_with_contractors = Job.query.filter(Job.contractor_id.isnot(None)).count()
            print(f"\nJobs with contractors: {jobs_with_contractors}")
            
            # Check completed jobs with contractors
            completed_jobs_with_contractors = Job.query.filter(
                Job.status == 'jc',
                Job.contractor_id.isnot(None)
            ).count()
            print(f"Completed jobs (jc) with contractors: {completed_jobs_with_contractors}")
            
            # Check if any completed jobs with contractors are already billed
            billed_jobs = Job.query.filter(
                Job.status == 'jc',
                Job.contractor_id.isnot(None),
                Job.bill_items.any()
            ).count()
            print(f"Completed jobs with contractors that are already billed: {billed_jobs}")
            
            # Check unbilled jobs
            unbilled_jobs = Job.query.filter(
                Job.status == 'jc',
                Job.contractor_id.isnot(None),
                ~Job.bill_items.any()
            ).count()
            print(f"Completed jobs with contractors that are NOT billed: {unbilled_jobs}")
            
            print("\n=== Sample Jobs ===")
            sample_jobs = Job.query.limit(5).all()
            for job in sample_jobs:
                print(f"Job ID: {job.id}, Status: {job.status}, Contractor ID: {job.contractor_id}, Has Bill Items: {len(job.bill_items) > 0}")
                
            print("\n=== Contractors ===")
            total_contractors = Contractor.query.count()
            print(f"Total contractors: {total_contractors}")
            
            logger.info("Job statistics analysis completed successfully")
            
    except Exception as e:
        logger.error(f"Error during job statistics analysis: {e}", exc_info=True)
        print(f"❌ Error occurred: {e}")
        sys.exit(1)
    finally:
        duration = time.time() - start_time
        logger.info(f"Script completed in {duration:.2f} seconds")

if __name__ == "__main__":
    main()