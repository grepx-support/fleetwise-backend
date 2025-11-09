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
        page_size = min(max(1, int(request.args.get('page_size', 50))), 100)
        
        # Validate required parameters
        if not driver_id:
            return jsonify({'error': 'driver_id is required'}), 400
            
        # Build query
        query = Job.query.filter_by(driver_id=driver_id, is_deleted=False)
        
        # Apply job IDs filter
        if job_ids:
            job_id_list = [int(id.strip()) for id in job_ids.split(',') if id.strip().isdigit()]
            if job_id_list:
                query = query.filter(Job.id.in_(job_id_list))
        
        # Apply customer name filter
        if customer_name:
            query = query.join(Customer, Job.customer_id == Customer.id)
            query = query.filter(Customer.name.ilike(f'%{customer_name}%'))
        
        # Apply contractor name filter
        if contractor_name:
            query = query.join(Contractor, Job.contractor_id == Contractor.id)
            query = query.filter(Contractor.name.ilike(f'%{contractor_name}%'))
        
        # Apply driver name filter (in case we want to search by driver name even when driver_id is specified)
        if driver_name_filter:
            query = query.join(Driver, Job.driver_id == Driver.id)
            query = query.filter(Driver.name.ilike(f'%{driver_name_filter}%'))
        
        # Apply date filters only if provided
        if start_date:
            query = query.filter(Job.pickup_date >= start_date)
        if end_date:
            query = query.filter(Job.pickup_date <= end_date)
            
        # Get total count
        total = query.count()
        
        # Apply pagination
        jobs = (
            query.order_by(Job.pickup_date.desc(), Job.pickup_time.desc())
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