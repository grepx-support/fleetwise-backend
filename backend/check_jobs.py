from app import create_app
from backend.models.job import Job
from backend.models.contractor import Contractor

app = create_app()
with app.app_context():
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
    from backend.models.bill import BillItem
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