from flask import Blueprint, request, jsonify
from backend.extensions import db
from backend.models.job import Job, JobStatus
from backend.models.driver import Driver
from backend.models.vehicle import Vehicle
from backend.models.customer import Customer
from backend.models.service import Service
from backend.models.invoice import Invoice
from backend.models.sub_customer import SubCustomer
import re
from datetime import datetime
import csv
import io

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/chat', methods=['POST'])
def chat_api():
    """Main chat API endpoint"""
    try:
        print(f"Chat API called at {datetime.now()}")
        print(f"Request method: {request.method}")
        print(f"Request headers: {dict(request.headers)}")
        
        data = request.get_json()
        print(f"Request data: {data}")
        
        message = data.get('message', '').lower().strip()
        print(f"Processed message: {message}")
        
        # Parse the message and generate response
        response, data = parse_chat_message(message)
        print(f"Generated response: {response}")
        print(f"Generated data length: {len(data) if data else 0}")
        
        return jsonify({
            'response': response,
            'data': data
        })
        
    except Exception as e:
        print(f"Chat API error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'response': f'Sorry, I encountered an error: {str(e)}',
            'data': None
        }), 500

@chat_bp.route('/chat/download', methods=['POST'])
def chat_download():
    """Download chat data as CSV"""
    try:
        data = request.get_json()
        query = data.get('query', '')
        table_data = data.get('data', [])
        
        if not table_data:
            return jsonify({'error': 'No data to download'}), 400
        
        # Create CSV content
        output = io.StringIO()
        if table_data:
            writer = csv.DictWriter(output, fieldnames=table_data[0].keys())
            writer.writeheader()
            writer.writerows(table_data)
        
        csv_content = output.getvalue()
        output.close()
        
        # Create response
        from flask import make_response
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename="{query.replace(" ", "_")}_{datetime.now().strftime("%Y%m%d")}.csv"'
        
        return response
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

def parse_chat_message(message):
    """Parse chat message and return appropriate response and data"""
    
    # Jobs queries
    if re.search(r'\b(all\s+)?jobs?\b', message):
        return handle_jobs_query(message)
    
    # Driver queries
    elif re.search(r'\bdrivers?\b', message):
        return handle_drivers_query(message)
    
    # Vehicle queries
    elif re.search(r'\bvehicles?\b', message):
        return handle_vehicles_query(message)
    
    # Customer queries
    elif re.search(r'\bcustomers?\b', message):
        return handle_customers_query(message)
    
    # Service queries
    elif re.search(r'\bservices?\b', message):
        return handle_services_query(message)
    
    # Invoice queries
    elif re.search(r'\binvoices?\b', message):
        return handle_invoices_query(message)
    
    # Status queries
    elif re.search(r'\bstatus\b', message):
        return handle_status_query(message)
    
    # Dashboard/Summary queries
    elif re.search(r'\b(dashboard|summary|overview)\b', message):
        return handle_dashboard_query(message)
    
    # About you queries
    elif re.search(r'\b(about you|who are you)\b', message):
        return handle_about_query(message)
    
    # Help
    elif re.search(r'\b(help|what can you do)\b', message):
        return handle_help_query(message)
    
    else:
        return "I'm not sure what you're asking for. Try asking about jobs, drivers, vehicles, customers, services, invoices, or status.", None

def handle_jobs_query(message):
    """Handle job-related queries"""
    
    if re.search(r'\bactive\b', message):
        jobs = Job.query.filter(
            Job.status.in_([JobStatus.NEW.value, JobStatus.CONFIRMED.value, JobStatus.OTW.value, JobStatus.OTS.value, JobStatus.POB.value]),
            Job.is_deleted == False
        ).limit(10).all()
        return f"I found {len(jobs)} active jobs:", [format_job(job) for job in jobs]
    
    elif re.search(r'\bpending\b', message):
        jobs = Job.query.filter(
            Job.status == JobStatus.PENDING.value,
            Job.is_deleted == False
        ).limit(10).all()
        return f"I found {len(jobs)} pending jobs:", [format_job(job) for job in jobs]
    
    elif re.search(r'\b(completed|yet to be invoiced)\b', message, re.IGNORECASE):
        jobs = Job.query.filter(
            Job.status.in_([JobStatus.JC.value, JobStatus.SD.value]),
            Job.is_deleted == False
        ).limit(10).all()
        return f"I found {len(jobs)} completed jobs:", [format_job(job) for job in jobs]
    
    elif re.search(r'\bcancelled\b', message):
        jobs = Job.query.filter(
            Job.status == JobStatus.CANCELED.value,
            Job.is_deleted == False
        ).limit(10).all()
        return f"I found {len(jobs)} cancelled jobs:", [format_job(job) for job in jobs]
    
    elif re.search(r'\bunpaid\b', message):
        # Jobs without invoices or with unpaid invoices
        jobs = Job.query.filter(
            Job.is_deleted == False,
            (Job.invoice_id.is_(None)) | 
            (Job.invoice_id.isnot(None) & Invoice.query.filter(Invoice.id == Job.invoice_id, Invoice.status == 'Unpaid').exists())
        ).limit(10).all()
        return f"I found {len(jobs)} unpaid jobs:", [format_job(job) for job in jobs]
    
    elif re.search(r'\bpaid\b', message):
        # Jobs with paid invoices
        jobs = Job.query.filter(
            Job.is_deleted == False,
            Job.invoice_id.isnot(None) & 
            Invoice.query.filter(Invoice.id == Job.invoice_id, Invoice.status == 'Paid').exists()
        ).limit(10).all()
        return f"I found {len(jobs)} paid jobs:", [format_job(job) for job in jobs]
    
    else:
        # All jobs
        jobs = Job.query.filter(Job.is_deleted == False).order_by(Job.id.desc()).limit(10).all()
        return f"I found {len(jobs)} recent jobs:", [format_job(job) for job in jobs]

def handle_drivers_query(message):
    """Handle driver-related queries"""
    
    if re.search(r'\bavailable\b', message):
        # Drivers not assigned to active jobs
        print("=== Available Drivers Debug ===")
        
        # Get all drivers first
        all_drivers = Driver.query.all()
        print(f"Total drivers in database: {len(all_drivers)}")
        
        # Get active jobs with drivers
        active_jobs = Job.query.filter(
            Job.status.in_([JobStatus.NEW.value, JobStatus.CONFIRMED.value, JobStatus.OTW.value, JobStatus.OTS.value, JobStatus.POB.value]),
            Job.is_deleted == False
        ).all()
        print(f"Active jobs found: {len(active_jobs)}")
        
        # Get driver IDs from active jobs
        active_driver_ids = db.session.query(Job.driver_id).filter(
            Job.status.in_([JobStatus.NEW.value, JobStatus.CONFIRMED.value, JobStatus.OTW.value, JobStatus.OTS.value, JobStatus.POB.value]),
            Job.is_deleted == False
        ).distinct().all()
        active_ids = [id[0] for id in active_driver_ids if id[0]]
        print(f"Active driver IDs: {active_ids}")
        
        # Get available drivers (not in active jobs)
        drivers = Driver.query.filter(~Driver.id.in_(active_ids)).all()
        print(f"Available drivers found: {len(drivers)}")
        
        # Also check if all drivers are available (when no active jobs)
        if len(active_ids) == 0:
            print("No active jobs found, all drivers should be available")
            drivers = Driver.query.all()
        
        return f"I found {len(drivers)} available drivers:", [format_driver(driver) for driver in drivers]
    
    else:
        print("=== All Drivers Debug ===")
        drivers = Driver.query.limit(10).all()
        print(f"Total drivers found: {len(drivers)}")
        for driver in drivers:
            print(f"Driver: ID={driver.id}, Name={driver.name}, Status={driver.status}")
        return f"I found {len(drivers)} drivers:", [format_driver(driver) for driver in drivers]

def handle_vehicles_query(message):
    """Handle vehicle-related queries"""
    
    if re.search(r'\bavailable\b', message):
        print("=== Available Vehicles Debug ===")
        
        # Get all vehicles first
        all_vehicles = Vehicle.query.all()
        print(f"Total vehicles in database: {len(all_vehicles)}")
        
        # Get active jobs with vehicles
        active_jobs = Job.query.filter(
            Job.status.in_([JobStatus.NEW.value, JobStatus.CONFIRMED.value, JobStatus.OTW.value, JobStatus.OTS.value, JobStatus.POB.value]),
            Job.is_deleted == False
        ).all()
        print(f"Active jobs found: {len(active_jobs)}")
        
        # Debug: Check job statuses
        job_statuses = db.session.query(Job.status).distinct().all()
        print(f"All job statuses in database: {[status[0] for status in job_statuses]}")
        
        # Debug: Show some active jobs
        for i, job in enumerate(active_jobs[:5]):  # Show first 5 active jobs
            print(f"Active job {i+1}: ID={job.id}, Status={job.status}, Vehicle={job.vehicle_id}")
        
        # Get vehicle IDs from active jobs
        active_vehicle_ids = [job.vehicle_id for job in active_jobs if job.vehicle_id]
        print(f"Active vehicle IDs: {active_vehicle_ids}")
        
        # Get available vehicles (not in active jobs)
        available_vehicles = Vehicle.query.filter(~Vehicle.id.in_(active_vehicle_ids)).all()
        print(f"Available vehicles found: {len(available_vehicles)}")
        
        # Also check if all vehicles are available (when no active jobs)
        if len(active_vehicle_ids) == 0:
            print("No active jobs found, all vehicles should be available")
            available_vehicles = Vehicle.query.all()
        
        # Debug: Show total jobs vs active jobs
        total_jobs = Job.query.filter(Job.is_deleted == False).count()
        print(f"Total jobs in database: {total_jobs}")
        print(f"Active jobs: {len(active_jobs)}")
        print(f"Completed jobs: {total_jobs - len(active_jobs)}")
        
        return f"I found {len(available_vehicles)} available vehicles:", [format_vehicle(vehicle) for vehicle in available_vehicles]
    
    else:
        print("=== All Vehicles Debug ===")
        vehicles = Vehicle.query.limit(10).all()
        print(f"Total vehicles found: {len(vehicles)}")
        for vehicle in vehicles:
            print(f"Vehicle: ID={vehicle.id}, Name={vehicle.name}, Number={vehicle.number}, Status={vehicle.status}")
        return f"I found {len(vehicles)} vehicles:", [format_vehicle(vehicle) for vehicle in vehicles]

def handle_customers_query(message):
    """Handle customer-related queries"""
    customers = Customer.query.limit(10).all()
    return f"I found {len(customers)} customers:", [format_customer(customer) for customer in customers]

def handle_services_query(message):
    """Handle service-related queries"""
    services = Service.query.limit(10).all()
    return f"I found {len(services)} services:", [format_service(service) for service in services]

def handle_invoices_query(message):
    """Handle invoice-related queries"""
    invoices = Invoice.query.limit(10).all()
    return f"I found {len(invoices)} invoices:", [format_invoice(invoice) for invoice in invoices]

def handle_status_query(message):
    """Handle status-related queries"""
    
    # Job status summary
    new_jobs = Job.query.filter(Job.status == JobStatus.NEW.value, Job.is_deleted == False).count()
    pending_jobs = Job.query.filter(Job.status == JobStatus.PENDING.value, Job.is_deleted == False).count()
    confirmed_jobs = Job.query.filter(Job.status == JobStatus.CONFIRMED.value, Job.is_deleted == False).count()
    completed_jobs = Job.query.filter(Job.status.in_([JobStatus.JC.value, JobStatus.SD.value]), Job.is_deleted == False).count()
    cancelled_jobs = Job.query.filter(Job.status == JobStatus.CANCELED.value, Job.is_deleted == False).count()
    
    return f"Job Status Summary:\n- New: {new_jobs}\n- Pending: {pending_jobs}\n- Confirmed: {confirmed_jobs}\n- Completed: {completed_jobs}\n- Cancelled: {cancelled_jobs}", None

def handle_dashboard_query(message):
    """Handle dashboard/summary queries"""
    
    # Overall summary
    total_jobs = Job.query.filter(Job.is_deleted == False).count()
    total_drivers = Driver.query.count()
    total_vehicles = Vehicle.query.count()
    total_customers = Customer.query.count()
    
    active_jobs = Job.query.filter(
        Job.status.in_([JobStatus.NEW.value, JobStatus.CONFIRMED.value, JobStatus.OTW.value, JobStatus.OTS.value, JobStatus.POB.value]),
        Job.is_deleted == False
    ).count()
    completed_jobs = Job.query.filter(
        Job.status.in_([JobStatus.JC.value, JobStatus.SD.value]),
        Job.is_deleted == False
    ).count()
    
    return f"Fleet Dashboard Summary:\n- Total Jobs: {total_jobs}\n- Active Jobs: {active_jobs}\n- Completed Jobs: {completed_jobs}\n- Total Drivers: {total_drivers}\n- Total Vehicles: {total_vehicles}\n- Total Customers: {total_customers}", None

def handle_about_query(message):
    """Handle about queries"""
    response = """I'm the Fleet Assistant, your AI-powered helper for managing fleet operations. I can help you with:

**Fleet Management:**
- View job statuses and details
- Check driver availability
- Monitor vehicle assignments
- Track customer information
- Manage service types
- Handle invoicing

**Quick Actions:**
- Get real-time summaries of your fleet
- Find available drivers and vehicles
- View job status reports
- Access dashboard summaries

Just click on any of the quick query buttons or ask me anything about your fleet operations!"""
    
    return response, None

def handle_help_query(message):
    """Handle help queries"""
    return """I can help you with the following queries:

**Jobs:**
- "Show all jobs"
- "Active jobs"
- "Pending jobs"
- "Yet to be invoiced jobs"
- "Cancelled jobs"

**Drivers:**
- "All drivers"
- "Available drivers"

**Vehicles:**
- "All vehicles"
- "Available vehicles"

**Others:**
- "All customers"
- "All services"
- "All invoices"
- "Job status"
- "Dashboard summary"
- "About you" - Ask me about my capabilities

Try asking me about any of these topics!""", None

# Data formatting functions
def format_job(job):
    return {
        'id': job.id,
        'customer_name': job.customer.name if job.customer else 'N/A',
        'pickup_location': job.pickup_location,
        'dropoff_location': job.dropoff_location,
        'status': job.status,
        'pickup_date': job.pickup_date,
        'driver_name': job.driver.name if job.driver else 'N/A',
        'vehicle_number': job.vehicle.number if job.vehicle else 'N/A',
        'service_type': job.service_type,
        'final_price': job.final_price
    }

def format_driver(driver):
    return {
        'id': driver.id,
        'name': driver.name,
        'mobile': driver.mobile,
        'email': driver.email,
        'status': driver.status
    }

def format_vehicle(vehicle):
    return {
        'id': vehicle.id,
        'name': vehicle.name,
        'number': vehicle.number,
        'type': vehicle.type,
        'status': vehicle.status
    }

def format_customer(customer):
    return {
        'id': customer.id,
        'name': customer.name,
        'email': customer.email,
        'mobile': customer.mobile,
        'status': customer.status
    }

def format_service(service):
    return {
        'id': service.id,
        'name': service.name,
        'description': service.description,
        'status': service.status
    }

def format_invoice(invoice):
    return {
        'id': invoice.id,
        'date': invoice.date.strftime('%Y-%m-%d') if invoice.date else 'N/A',
        'total_amount': invoice.total_amount,
        'status': invoice.status,
        'customer_id': invoice.customer_id
    } 