from flask import Blueprint, request, jsonify
from backend.services.driver_service import DriverService
from backend.services.job_service import JobService
from backend.schemas.job_schema import JobSchema
from flask_security.decorators import roles_accepted
import logging
from backend.extensions import db
from backend.models.job import Job
from backend.models.customer import Customer
from backend.models.contractor import Contractor
from backend.models.driver import Driver
from datetime import datetime

reports_bp = Blueprint('reports', __name__)
job_schema_many = JobSchema(many=True)

@reports_bp.route('/reports/driver', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def driver_job_history():
    """
    Get job history for a specific driver with additional filters.
    
    Query Parameters:
    - driver_id (int): ID of the driver (required)
    - job_ids (string): Comma-separated list of job IDs (optional)
    - customer_name (string): Filter by customer name (optional)
    - contractor_name (string): Filter by contractor name (optional)
    - driver_name (string): Filter by driver name (optional)
    - start_date (string): Start date in YYYY-MM-DD format (optional)
    - end_date (string): End date in YYYY-MM-DD format (optional)
    - page (int, optional): Page number (default: 1)
    - page_size (int, optional): Number of records per page (default: 50, max: 100)
    
    Returns:
    - JSON with paginated job list and total count
    """
    try:
        # Get query parameters
        driver_id = request.args.get('driver_id', type=int)
        job_ids = request.args.get('job_ids')
        customer_name = request.args.get('customer_name')
        contractor_name = request.args.get('contractor_name')
        driver_name_filter = request.args.get('driver_name')  # Renamed to avoid conflict
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        page = max(1, int(request.args.get('page', 1)))
        page_size = max(1, int(request.args.get('page_size', 50)))
        # Set a reasonable upper limit for exports while preventing abuse
        page_size = min(page_size, 5000)
    
    # Validate required parameters
        if not driver_id:
            return jsonify({'error': 'driver_id is required'}), 400
            
        # Build query - Always left join contractor and driver tables to get their names
        query = Job.query.filter_by(driver_id=driver_id, is_deleted=False)
        query = query.outerjoin(Contractor, Job.contractor_id == Contractor.id)
        query = query.outerjoin(Driver, Job.driver_id == Driver.id)
        
        # Apply job IDs filter
        if job_ids:
            job_id_list = [int(id.strip()) for id in job_ids.split(',') if id.strip().isdigit()]
            if job_id_list:
                query = query.filter(Job.id.in_(job_id_list))
        
        # Apply customer name filter
        if customer_name:
            query = query.join(Customer, Job.customer_id == Customer.id)
            # Escape special characters for LIKE patterns to prevent SQL injection
            safe_customer_name = customer_name.replace('%', '\\%').replace('_', '\\_')
            query = query.filter(Customer.name.ilike(f'%{safe_customer_name}%', escape='\\'))
        
        # Apply contractor name filter
        if contractor_name:
            # Only apply contractor filter if contractor_name is provided
            # Escape special characters for LIKE patterns to prevent SQL injection
            safe_contractor_name = contractor_name.replace('%', '\\%').replace('_', '\\_')
            query = query.filter(Contractor.name.ilike(f'%{safe_contractor_name}%', escape='\\'))
        
        # Apply driver name filter only when driver_id is not provided
        # This prevents conflicts between driver_id and driver_name filters
        if driver_name_filter and not driver_id:
            # Escape special characters for LIKE patterns to prevent SQL injection
            safe_driver_name = driver_name_filter.replace('%', '\\%').replace('_', '\\_')
            query = query.filter(Driver.name.ilike(f'%{safe_driver_name}%', escape='\\'))
        # Log warning if both driver_id and driver_name are provided
        elif driver_name_filter and driver_id:
            logging.warning(f"Both driver_id ({driver_id}) and driver_name ('{driver_name_filter}') provided; driver_name filter ignored to prevent conflicts")
        
        # Apply date filters only if provided with proper validation
        if start_date:
            try:
                from datetime import datetime
                start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
                query = query.filter(Job.pickup_date >= start_dt)
            except ValueError:
                return jsonify({'error': 'Invalid start_date format. Use YYYY-MM-DD'}), 400
        if end_date:
            try:
                from datetime import datetime
                end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
                query = query.filter(Job.pickup_date <= end_dt)
            except ValueError:
                return jsonify({'error': 'Invalid end_date format. Use YYYY-MM-DD'}), 400
            
        # Get total count
        total = query.count()
        
        # Apply pagination
        jobs = (
            query.options(
                db.joinedload(Job.contractor),
                db.joinedload(Job.driver)
            )
            .order_by(Job.pickup_date.desc(), Job.pickup_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        
        # Serialize jobs
        jobs_data = job_schema_many.dump(jobs)
        
        return jsonify({
            'items': jobs_data,
            'total': total,
            'page': page,
            'page_size': page_size
        }), 200
        
    except ValueError as ve:
        return jsonify({'error': 'Invalid pagination parameters'}), 400
    except Exception as e:
        logging.error(f"Error in driver_job_history: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500