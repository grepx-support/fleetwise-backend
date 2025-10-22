import logging
import json
import pytz
from backend.extensions import db
from backend.models.job import Job
from backend.models.customer import Customer
from backend.models.vehicle import Vehicle
from backend.models.driver import Driver
from backend.models.user import User
from backend.models.invoice import Invoice
from backend.models.customer_service_pricing import CustomerServicePricing
from backend.models.contractor_service_pricing import ContractorServicePricing
from backend.models.service import Service
from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice
from backend.models.vehicle_type import VehicleType
from datetime import datetime
from backend.services.push_notification_service import PushNotificationService
from decimal import Decimal


def compare_job_fields(old_job, new_data):
    """
    Compare all relevant fields between the old job object and the new data dict.
    Returns a list of (field, old_val, new_val) for changed fields.
    """
    data_fields = set(new_data.keys())
    # Also include any custom fields that are explicitly provided
    custom_fields = set()
    if 'extra_services' in new_data and hasattr(old_job, 'extra_services_data'):
        custom_fields.add('extra_services')
    # Only compare fields that are actually present in the update data
    fields_to_compare = data_fields | custom_fields

    changed_fields = []
    for field in fields_to_compare:
        # Special handling for extra_services (list/dict)
        if field == 'extra_services':
            old_val = getattr(old_job, 'extra_services_data', None)
            new_val = new_data.get('extra_services', None)
            # Compare as JSON for deep equality
            try:
                old_json = json.dumps(old_val, sort_keys=True, default=str) if old_val is not None else None
                new_json = json.dumps(new_val, sort_keys=True, default=str) if new_val is not None else None
            except Exception:
                old_json = str(old_val)
                new_json = str(new_val)
            if old_json != new_json:
                changed_fields.append((field, old_val, new_val))
        else:
            old_val = getattr(old_job, field, None)
            new_val = new_data.get(field, None)
            # For lists/dicts, compare as JSON
            if isinstance(old_val, (list, dict)) or isinstance(new_val, (list, dict)):
                try:
                    old_json = json.dumps(old_val, sort_keys=True, default=str) if old_val is not None else None
                    new_json = json.dumps(new_val, sort_keys=True, default=str) if new_val is not None else None
                except Exception:
                    old_json = str(old_val)
                    new_json = str(new_val)
                if old_json != new_json:
                    changed_fields.append((field, old_val, new_val))
            else:
                if old_val != new_val:
                    changed_fields.append((field, old_val, new_val))
    return changed_fields

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class JobService:
    @staticmethod
    def check_driver_conflict(driver_id, pickup_date, pickup_time, job_id=None, time_buffer_minutes=60):
        """
        Check if a driver already has a job scheduled at the same date and time with a configurable buffer.
        
        Args:
            driver_id: ID of the driver to check
            pickup_date: Date of the job (YYYY-MM-DD format)
            pickup_time: Time of the job (HH:MM format)
            job_id: Optional job ID to exclude (for updates)
            time_buffer_minutes: Buffer time in minutes before and after job (default 60 minutes)
            
        Returns:
            Job object if conflict found, None otherwise
        """
        try:
            from datetime import date, timedelta
            
            # Query for jobs with the same driver across relevant dates
            active_statuses = ['new', 'pending', 'confirmed', 'otw', 'ots', 'pob']
            
            # For large buffers, we need to check adjacent dates as well
            base_date = date.fromisoformat(pickup_date)
            query_dates = [base_date]
            if time_buffer_minutes >= 60:
                query_dates.extend([base_date - timedelta(days=1), base_date + timedelta(days=1)])
            
            query = Job.query.filter(
                Job.driver_id == driver_id,
                Job.pickup_date.in_([d.strftime('%Y-%m-%d') for d in query_dates]),
                Job.status.in_(active_statuses)
            )
            
            # Exclude the current job if updating
            if job_id:
                query = query.filter(Job.id != job_id)
                
            # Get all jobs for this driver on these dates
            jobs = query.all()
            
            # Convert pickup_time to minutes for comparison
            def time_to_minutes(time_str):
                try:
                    if not isinstance(time_str, str) or len(time_str) != 5 or time_str[2] != ':':
                        raise ValueError("Invalid time format")
                    hours, minutes = map(int, time_str.split(':'))
                    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
                        raise ValueError("Invalid time values")
                    return hours * 60 + minutes
                except ValueError as e:
                    raise ServiceError(f"Invalid pickup_time format: {str(e)}. Expected HH:MM.")
            
            # Convert the new job's time to minutes
            new_job_minutes = time_to_minutes(pickup_time)
            
            # Check if any job conflicts with the new job within the buffer
            for job in jobs:
                job_minutes = time_to_minutes(job.pickup_time)
                
                # For jobs on different dates, we need to adjust the time calculation
                job_date = date.fromisoformat(job.pickup_date)
                date_diff_days = (job_date - base_date).days
                
                # Adjust job minutes based on date difference
                adjusted_job_minutes = job_minutes + (date_diff_days * 24 * 60)
                
                # Check if the times overlap within the buffer
                if abs(new_job_minutes - adjusted_job_minutes) <= time_buffer_minutes:
                    return job
                    
            return None
        except Exception as e:
            logging.error(f"Error checking driver conflict: {e}", exc_info=True)
            return None

    @staticmethod
    def get_all():
        try:
            # Load vehicle_type relationship for table view
            query = Job.get_with_relationships(include_relationships=['customer', 'driver', 'vehicle', 'vehicle_type'])
            # Load vehicle_type relationship for table view
            query = Job.get_with_relationships(include_relationships=['customer', 'driver', 'vehicle', 'vehicle_type'])
            if query is None:
                return []
            # Filter out deleted jobs
            return query.filter(Job.is_deleted.is_(False)).all()
        except Exception as e:
            logging.error(f"Error fetching jobs: {e}", exc_info=True)
            raise ServiceError("Could not fetch jobs. Please try again later.")

    @staticmethod
    def get_by_id(job_id):
        try:
            # Load all relationships for detailed view
            return Job.get_with_relationships(job_id, include_relationships=['customer', 'driver', 'vehicle', 'service', 'invoice'])
        except Exception as e:
            logging.error(f"Error fetching job: {e}", exc_info=True)
            raise ServiceError("Could not fetch job. Please try again later.")

    @staticmethod
    def get_by_driver(driver_id):
        try:
            # Use optimized loading for list views - load most commonly accessed relationships
            query = Job.get_with_relationships(include_relationships=['customer', 'driver', 'vehicle'])
            if query is None:
                return []
            # Filter out deleted jobs
            return query.filter(Job.driver_id == driver_id, Job.is_deleted.is_(False)).all()
        except Exception as e:
            logging.error(f"Error fetching jobs for driver: {e}", exc_info=True)
            raise ServiceError("Could not fetch jobs. Please try again later.")

    @staticmethod
    def get_by_customer(customer_id):
        try:
            # Use optimized loading for list views - load most commonly accessed relationships
            query = Job.get_with_relationships(include_relationships=['customer', 'driver', 'vehicle'])
            if query is None:
                return []
            # Filter out deleted jobs
            return query.filter(Job.customer_id == customer_id, Job.is_deleted.is_(False)).all()
        except Exception as e:
            logging.error(f"Error fetching jobs for customer: {e}", exc_info=True)
            raise ServiceError("Could not fetch jobs. Please try again later.")

   
    @staticmethod
    def create(data):
        try:
            # Validate driver-vehicle relationship if both are provided
            driver_id = data.get('driver_id')
            vehicle_id = data.get('vehicle_id')
            contractor_id = data.get('contractor_id')

            if driver_id and vehicle_id:
                driver = Driver.query.get(driver_id)
                if driver and driver.vehicle_id != vehicle_id:
                    raise ServiceError("Selected driver is not assigned to the selected vehicle")

            # Enforce contractor requirement for confirmed status
            if not contractor_id:
                # If no contractor, status cannot be confirmed - must be pending or new
                if data.get('status') == 'confirmed':
                    raise ServiceError("Contractor is required for confirmed jobs")
                data['status'] = 'pending' if (driver_id and vehicle_id) else data.get('status', 'new')
            elif not driver_id or not vehicle_id:
                # Has contractor but missing driver/vehicle
                data['status'] = 'pending'
            # else: has all three (contractor, driver, vehicle) - status can be confirmed if requested

            # Handle extra_services - calculate extra_charges ONCE
            extra_services_data = []
            if 'extra_services' in data:
                if isinstance(data['extra_services'], str):
                    try:
                        extra_services_data = json.loads(data['extra_services'])
                    except (json.JSONDecodeError, TypeError):
                        extra_services_data = []
                elif isinstance(data['extra_services'], list):
                    extra_services_data = data['extra_services']
                data.pop('extra_services', None)

            # Calculate extra charges from extra services
            extra_charges = 0.0
            if extra_services_data:
                for service in extra_services_data:
                    if isinstance(service, dict) and 'price' in service:
                        extra_charges += float(service['price'])

            # Set the extra_charges in data if not already set or if we have extra services
            if extra_charges > 0:
                data['extra_charges'] = data.get('extra_charges', 0) + extra_charges

            # Ensure base_price is numeric, but allow 0 to enable manual updates
            base_price = data.get('base_price')
            try:
                base_price = float(base_price)
            except (TypeError, ValueError):
                base_price = 0.0
            data['base_price'] = base_price

            # VEHICLE TYPE LOGIC: set vehicle_type_id from data or from vehicle
            vehicle_type_id = data.get('vehicle_type_id')
            vehicle_type = None
            if not vehicle_type_id and vehicle_id:
                vehicle = Vehicle.query.get(vehicle_id)
                if vehicle and hasattr(vehicle, 'vehicle_type_id'):
                    vehicle_type_id = vehicle.vehicle_type_id
            data['vehicle_type_id'] = vehicle_type_id
            
            # Get vehicle_type name for price calculation
            if vehicle_type_id:
                vehicle_type_obj = VehicleType.query.get(vehicle_type_id)
                if vehicle_type_obj:
                    vehicle_type = vehicle_type_obj.name

            # Initialize customer_pricing to None
            customer_pricing = None
            
            # Fetch customer service pricing data if both customer_id and service_type are provided
            if data.get('customer_id') and data.get('service_type'):
                service = Service.query.filter_by(name=data.get('service_type')).first()
                if service:
                    # First, try to get customer service pricing with vehicle type
                    if vehicle_type_id:
                        customer_pricing = CustomerServicePricing.query.filter_by(
                            cust_id=data.get('customer_id'),
                            service_id=service.id,
                            vehicle_type_id=vehicle_type_id
                        ).first()
                    
                    # If not found, try without vehicle type (backward compatibility)
                    if not customer_pricing:
                        customer_pricing = CustomerServicePricing.query.filter_by(
                            cust_id=data.get('customer_id'),
                            service_id=service.id
                        ).first()

            # Helper for safe float conversion
            def safe_float(value, default=0.0):
                try:
                    return float(value) if value not in (None, "") else default
                except (TypeError, ValueError):
                    return default

            # Build price_data for calculation
            price_data = {
                'customer_id': data.get('customer_id'),
                'vehicle_type': vehicle_type,
                'vehicle_type_id': vehicle_type_id,
                'service_type': data.get('service_type'),
                'base_price': base_price,
                'pickup_time': data.get('pickup_time'),
                'midnight_surcharge': data.get('midnight_surcharge', 0),
                'additional_discount': data.get('additional_discount', 0),
                'extra_charges': data.get('extra_charges', 0),  # Use calculated extra_charges
            }
            
            # Update base_price from customer pricing if not manually set
            if customer_pricing and customer_pricing.price is not None and base_price == 0:
                price_data['base_price'] = float(customer_pricing.price)
                data['base_price'] = float(customer_pricing.price)

            # Assign pickup/dropoff locations safely
            for i in range(1, 6):
                pickup_field = f'pickup_loc{i}'
                dropoff_field = f'dropoff_loc{i}'
                pickup_price_field = f'pickup_loc{i}_price'
                dropoff_price_field = f'dropoff_loc{i}_price'

                if hasattr(Job, pickup_field):
                    price_data[pickup_field] = data.get(pickup_field) or (data.get('pickup_location') if i == 1 else None)
                else:
                    logging.warning(f"{pickup_field} field not found in Job model")

                if hasattr(Job, dropoff_field):
                    price_data[dropoff_field] = data.get(dropoff_field) or (data.get('dropoff_location') if i == 1 else None)
                else:
                    logging.warning(f"{dropoff_field} field not found in Job model")

                price_data[pickup_price_field] = safe_float(data.get(pickup_price_field, 0)) if hasattr(Job, pickup_price_field) else 0
                price_data[dropoff_price_field] = safe_float(data.get(dropoff_price_field, 0)) if hasattr(Job, dropoff_price_field) else 0

            # Calculate final price
            price_result = JobService.calculate_price(price_data, vehicle_type_id)
            if isinstance(price_result, dict) and price_result.get('error'):
                raise ServiceError(price_result['error'])
            data['final_price'] = price_result['final_price']

            # Populate job_cost from ContractorServicePricing when contractor + service present
            try:
                contractor_id = data.get('contractor_id')
                svc_id = data.get('service_id')
                if not svc_id and data.get('service_type'):
                    svc = Service.query.filter_by(name=data.get('service_type')).first()
                    svc_id = svc.id if svc else None
                if contractor_id and svc_id:
                    cpricing = ContractorServicePricing.query.filter_by(contractor_id=contractor_id, service_id=svc_id).first()
                    if cpricing and cpricing.cost is not None:
                        data['job_cost'] = float(cpricing.cost)
                    else:
                        logging.warning(f"No contractor pricing found for contractor_id={contractor_id}, service_id={svc_id}")
            except (ValueError, TypeError) as e:
                logging.warning(f"Invalid contractor pricing value for contractor_id={data.get('contractor_id')}: {e}")
            except Exception as e:
                logging.error(f"Failed to populate job_cost during create: {e}", exc_info=True)
                raise ServiceError(f"Failed to populate job_cost: {str(e)}")

            # Create job
            job = Job(**data)
            job.extra_services_data = extra_services_data

            db.session.add(job)
            db.session.commit()

            # Push notification if driver assigned
            if driver_id:
                try:
                    driver = Driver.query.get(driver_id)
                    if driver:
                        user = User.query.filter_by(driver_id=driver.id).first()
                        if user:
                            for token in [user.android_device_token, user.ios_device_token]:
                                if token:
                                    PushNotificationService.send(
                                        token=token,
                                        title="New Job Assigned",
                                        body=f"Hi {driver.name}, a new job has been assigned to you.",
                                        data={"job_id": str(job.id)}
                                    )
                except Exception as e:
                    logging.warning(f"Failed to send push notification for job {job.id}: {e}")

            return job

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating job: {e}", exc_info=True)
            raise ServiceError("Could not create job. Please try again later.")
    
    @staticmethod
    def update(job_id, data):
        try:
            # Log all changed fields (full job field comparison) - DO THIS ONCE
            job_for_compare = Job.query.get(job_id)
            if job_for_compare:
                all_changes = compare_job_fields(job_for_compare, data)
                if all_changes:
                    # Store audit record
                    try:
                        from backend.models.job_audit import JobAudit
                        from datetime import datetime
                        from flask_security.utils import current_user
                        
                        def convert_dt(obj):
                            if isinstance(obj, dict):
                                return {k: convert_dt(v) for k, v in obj.items()}
                            elif isinstance(obj, list):
                                return [convert_dt(i) for i in obj]
                            elif isinstance(obj, datetime):
                                return obj.isoformat()
                            else:
                                return obj

                        user_id = data.get('user_id')
                        if not user_id and hasattr(current_user, 'id') and current_user.is_authenticated:
                            user_id = current_user.id
                        reason = data.get('reason')
                        if not reason:
                            reason = "Job updated"
                        audit_data = {
                            "fields_changed": [
                                {"field": field, "old": convert_dt(old), "new": convert_dt(new)}
                                for field, old, new in all_changes
                            ]
                        }
                        audit_record = JobAudit()
                        audit_record.job_id = job_id
                        audit_record.changed_by = user_id
                        audit_record.old_status = getattr(job_for_compare, 'status', None)
                        audit_record.new_status = data.get('status', getattr(job_for_compare, 'status', None))
                        audit_record.additional_data = audit_data
                        audit_record.reason = reason
                        audit_record.changed_at = datetime.now(pytz.timezone('Asia/Singapore'))  # Singapore local time
                        db.session.add(audit_record)
                        db.session.flush()  # Force flush to DB
                        # Do not commit here; let main commit handle it
                    except Exception as e:
                        logging.warning(f"Failed to create audit record for job {job_id}: {e}")
            # Validate driver-vehicle relationship if both are provided
            driver_id = data.get('driver_id')
            vehicle_id = data.get('vehicle_id')
            contractor_id = data.get('contractor_id')

            if driver_id and vehicle_id:
                driver = Driver.query.get(driver_id)
                if driver and driver.vehicle_id != vehicle_id:
                    raise ServiceError("Selected driver is not assigned to the selected vehicle")

            # Enforce contractor requirement for confirmed status
            if not contractor_id:
                # If no contractor, status cannot be confirmed - must be pending or new
                if data.get('status') == 'confirmed':
                    raise ServiceError("Contractor is required for confirmed jobs")
                # Auto-set status based on what we have
                if 'status' not in data:  # Only auto-set if status not explicitly provided
                    data['status'] = 'pending' if (driver_id and vehicle_id) else 'new'
            elif not driver_id or not vehicle_id:
                # Has contractor but missing driver/vehicle
                if 'status' not in data:  # Only auto-set if status not explicitly provided
                    data['status'] = 'pending'
            # else: has all three (contractor, driver, vehicle) - status can be confirmed if requested

            # Handle extra_services
            extra_services_data = []
            if 'extra_services' in data:
                if isinstance(data['extra_services'], str):
                    try:
                        extra_services_data = json.loads(data['extra_services'])
                    except (json.JSONDecodeError, TypeError):
                        extra_services_data = []
                elif isinstance(data['extra_services'], list):
                    extra_services_data = data['extra_services']
                else:
                    extra_services_data = []

                # Always calculate extra_charges from extra_services
                extra_charges_from_services = 0.0
                if extra_services_data:
                    for service in extra_services_data:
                        if isinstance(service, dict) and 'price' in service:
                            extra_charges_from_services += float(service['price'])
                data['extra_charges'] = extra_charges_from_services

                # Remove extra_services from data as it's not a direct job field
                data.pop('extra_services', None)

            # Pricing fields to check - includes ALL fields that affect final_price calculation
            pricing_fields = [
                'customer_id', 'service_type', 'vehicle_id', 'vehicle_type_id',  # Key fields that affect pricing
                'pickup_loc1', 'pickup_loc2', 'pickup_loc3', 'pickup_loc4', 'pickup_loc5',
                'pickup_loc1_price', 'pickup_loc2_price', 'pickup_loc3_price', 'pickup_loc4_price', 'pickup_loc5_price',
                'dropoff_loc1', 'dropoff_loc2', 'dropoff_loc3', 'dropoff_loc4', 'dropoff_loc5',
                'dropoff_loc1_price', 'dropoff_loc2_price', 'dropoff_loc3_price', 'dropoff_loc4_price', 'dropoff_loc5_price',
                'base_price', 'extra_services', 'midnight_surcharge', 'extra_charges', 'additional_discount',
                'additional_stop_count', 'stop_charge', 'pickup_time'  # Additional fields affecting price
            ]

            # Use transaction with row-level locking
            job = Job.query.with_for_update().get(job_id)
            if not job:
                return None

            # Track changed fields and determine if pricing needs update
            needs_pricing_update = False
            changed_fields = []
            for field in pricing_fields:
                if field in data:
                    new_val = data[field]
                    old_val = getattr(job, field, None)
                    # For floats, allow small tolerance
                    if isinstance(new_val, float) or isinstance(old_val, float):
                        try:
                            if abs(float(new_val or 0) - float(old_val or 0)) > 1e-6:
                                needs_pricing_update = True
                                changed_fields.append((field, old_val, new_val))
                        except Exception:
                            needs_pricing_update = True
                            changed_fields.append((field, old_val, new_val))
                    else:
                        if new_val != old_val:
                            needs_pricing_update = True
                            changed_fields.append((field, old_val, new_val))

            # Handle extra_services
            job.extra_services_data = extra_services_data

            # Update job fields
            for key, value in data.items():
                setattr(job, key, value)

            # Recalculate final_price only if a pricing field value changed
            if needs_pricing_update:
                vehicle_type = None
                vehicle_type_id = None
                if data.get('vehicle_id') or job.vehicle_id:
                    vid = data.get('vehicle_id') or job.vehicle_id
                    vehicle = Vehicle.query.get(vid)
                    if vehicle:
                        vehicle_type = vehicle.type
                        vehicle_type_obj = VehicleType.query.filter_by(name=vehicle_type).first()
                        if vehicle_type_obj:
                            vehicle_type_id = vehicle_type_obj.id

                explicit_final_price = data.get('final_price')
                core_pricing_fields = {'base_price', 'customer_id', 'service_type', 'vehicle_id'}
                core_fields_changed = any(
                    (field in data and data[field] != getattr(job, field, None))
                    for field in core_pricing_fields
                )

                if explicit_final_price is not None and not core_fields_changed:
                    job.final_price = explicit_final_price
                else:
                    price_data = {
                        'customer_id': data.get('customer_id') or job.customer_id,
                        'service_type': data.get('service_type') or job.service_type,
                        'vehicle_id': data.get('vehicle_id') or job.vehicle_id,
                        'base_price': data.get('base_price') if 'base_price' in data else getattr(job, 'base_price', 0),
                        'pickup_time': data.get('pickup_time') or getattr(job, 'pickup_time', None),
                        'midnight_surcharge': data.get('midnight_surcharge', getattr(job, 'midnight_surcharge', 0)),
                        'additional_discount': data.get('additional_discount', getattr(job, 'additional_discount', 0)),
                        'extra_charges': data.get('extra_charges', getattr(job, 'extra_charges', 0)),
                        'extra_services': getattr(job, 'extra_services_data', [])
                    }

                    # Add location prices - ensure all are included even if not in update payload
                    for i in range(1, 6):
                        pickup_price_field = f'pickup_loc{i}_price'
                        dropoff_price_field = f'dropoff_loc{i}_price'
                        pickup_loc_field = f'pickup_loc{i}'
                        dropoff_loc_field = f'dropoff_loc{i}'

                        # Prefer data value, fall back to job value, default to 0
                        price_data[pickup_price_field] = data.get(pickup_price_field, getattr(job, pickup_price_field, 0) or 0)
                        price_data[dropoff_price_field] = data.get(dropoff_price_field, getattr(job, dropoff_price_field, 0) or 0)
                        price_data[pickup_loc_field] = data.get(pickup_loc_field, getattr(job, pickup_loc_field, None))
                        price_data[dropoff_loc_field] = data.get(dropoff_loc_field, getattr(job, dropoff_loc_field, None))

                    # Fetch customer service pricing data if both customer_id and service_type are provided
                    if data.get('customer_id') or job.customer_id:
                        customer_id = data.get('customer_id') or job.customer_id
                        service_type = data.get('service_type') or job.service_type
                        if customer_id and service_type:
                            service = Service.query.filter_by(name=service_type).first()
                            if service:
                                customer_pricing = None
                                if vehicle_type_id:
                                    customer_pricing = CustomerServicePricing.query.filter_by(
                                        cust_id=customer_id,
                                        service_id=service.id,
                                        vehicle_type_id=vehicle_type_id
                                    ).first()
                                if not customer_pricing:
                                    customer_pricing = CustomerServicePricing.query.filter_by(
                                        cust_id=customer_id,
                                        service_id=service.id
                                    ).first()


                    price_result = JobService.calculate_price(price_data, vehicle_type_id)
                    if isinstance(price_result, dict) and price_result.get('error'):
                        raise ServiceError(price_result['error'])
                    job.final_price = price_result['final_price']

                # Update job_cost from ContractorServicePricing if contractor/service provided
                try:
                    contractor_id = data.get('contractor_id') or getattr(job, 'contractor_id', None)
                    svc_id = data.get('service_id') or getattr(job, 'service_id', None)
                    if contractor_id and svc_id:
                        cpricing = ContractorServicePricing.query.filter_by(
                            contractor_id=contractor_id, 
                            service_id=svc_id
                        ).first()
                        if cpricing and cpricing.cost is not None:
                            job.job_cost = float(cpricing.cost)
                        else:
                            logging.warning(f"No contractor pricing found for contractor_id={contractor_id}, service_id={svc_id} while updating job {job_id}")
                except (ValueError, TypeError) as e:
                    logging.warning(f"Invalid contractor pricing value for contractor_id={data.get('contractor_id')} on job {job_id}: {e}")
                except Exception as e:
                    logging.error(f"Failed to populate job_cost during update for job {job_id}: {e}", exc_info=True)
                    raise ServiceError(f"Failed to populate job_cost: {str(e)}")

            db.session.commit()
            return job

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating job: {e}", exc_info=True)
            raise ServiceError("Could not update job. Please try again later.")
        
    
    @staticmethod
    def delete(job_id, soft=True):
        """
        Delete or soft-delete a job.
        
        Args:
            job_id: ID of job to delete
            soft: If True, marks job as deleted. If False, permanently removes job.
            
        Returns:
            bool: True if successful
        """
        try:
            job = Job.query.get(job_id)
            if not job:
                return False
            if soft:
                # Implement soft delete
                job.is_deleted = True
            else:
                # Implement hard delete
                db.session.delete(job)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting job: {e}", exc_info=True)
            raise ServiceError("Could not delete job. Please try again later.")

   
    
    @staticmethod
    def calculate_price(data: dict, vehicle_type_id=None):
        try:
            # Base price
            base_price = 0
            customer_id = data.get('customer_id')
            service_type = data.get('service_type')
            
            if customer_id and service_type and vehicle_type_id:
                service = Service.query.filter_by(name=service_type).first()
                if service:
                    customer_pricing = CustomerServicePricing.query.filter_by(
                        cust_id=customer_id,
                        service_id=service.id,
                        vehicle_type_id=vehicle_type_id
                    ).first()
                    if customer_pricing and customer_pricing.price is not None:
                        base_price = customer_pricing.price
            elif data.get("base_price"):
                base_price = safe_float(data.get("base_price"))
            
            data["base_price"] = base_price
            final_price = base_price
            
            # Location prices (pickup and dropoff)
            for i in range(1, 6):
                pickup_price_field = f'pickup_loc{i}_price'
                dropoff_price_field = f'dropoff_loc{i}_price'
                final_price += safe_float(data.get(pickup_price_field, 0))
                final_price += safe_float(data.get(dropoff_price_field, 0))
            # Midnight surcharge - always validate against pickup_time for consistency
            midnight_surcharge = 0.0
            if data.get('pickup_time'):
                try:
                    hour, minute = map(int, data['pickup_time'].split(':'))
                    # Midnight period: 23:00-06:59
                    is_midnight_period = (hour >= 23 or hour < 7)
                    if is_midnight_period:
                        # Use provided surcharge value if given, else default to 15.0
                        midnight_surcharge = safe_float(data.get('midnight_surcharge', 15.0))
                    # else: outside midnight period, surcharge is 0 regardless of what was passed
                except (ValueError, AttributeError):
                    logging.warning(f"Invalid pickup_time format: {data.get('pickup_time')}")
                    midnight_surcharge = 0.0
            else:
                # No pickup_time provided, use explicit surcharge value if given
                midnight_surcharge = safe_float(data.get('midnight_surcharge', 0))
            final_price += midnight_surcharge
            # Add extra charges (which now includes extra service prices)
            final_price += safe_float(data.get("extra_charges", 0))
            # Apply discounts
            final_price -= safe_float(data.get("additional_discount", 0))
            
            return {"final_price": round(final_price, 2)}
        except ServiceError as se:
            return {"error": str(se)}
        except Exception as e:
            return {"error": "Failed to calculate price."}

    

    @staticmethod
    def set_penalty(job_id, penalty):
        try:
            job = Job.query.get(job_id)
            if not job:
                return {'error': 'Job not found'}
            job.penalty = penalty
            db.session.commit()
            return {'success': True}
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error setting penalty for job: {e}", exc_info=True)
            raise ServiceError("Could not set penalty for job. Please try again later.") 
        
    @staticmethod
    def remove_job_from_invoice(job_id):
        try:
            job = Job.query.get(job_id)
            if not job:
                 raise ServiceError("Job not found")
        
            if job.invoice_id is None:
                raise ServiceError("Job does not belong to any invoice")

            invoice = Invoice.query.get(job.invoice_id)
            if not invoice:
                raise ServiceError("error': Associated invoice not found")

            if job.final_price:
                #invoice.total_amount = max((invoice.total_amount or 0) - job.final_price, 0)
                invoice.total_amount = max((invoice.total_amount or Decimal('0.00')) - Decimal(str(job.final_price)), Decimal('0.00'))

            job.invoice_id = None

            remaining_jobs = Job.query.filter(Job.invoice_id == job.invoice_id, Job.is_deleted.is_(False)).all()

            if not remaining_jobs and (invoice.total_amount == 0 or invoice.total_amount is None):
                db.session.delete(invoice)
                msg = 'Job removed and empty invoice deleted'
            else:
                msg = 'Job removed from invoice'
            db.session.commit()
            return {'success': True}
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error removing job from invoice: {e}", exc_info=True)
            raise ServiceError("Could not remove job from invoice. Please try again later.")
    
    @staticmethod
    def updateJobAndInvoice(job_id, data):
        try:
            job = Job.query.get(job_id)
            if not job:
                return None
            ALLOWED_UPDATE_FIELDS = {'final_price', 'status', 'pickup_location', 'dropoff_location'}
            for key, value in data.items():
                if key in ALLOWED_UPDATE_FIELDS:
                    setattr(job, key, value)
                else:
                    raise ServiceError(f"Field '{key}' is not allowed for update")
            invoice = Invoice.query.get(job.invoice_id)
            if not invoice:
                return {'error': 'No Invoice found for this Job.'}
            jobs = Job.query.filter(Job.invoice_id == job.invoice_id).all()
            if not jobs:
                return {'error': 'No jobs found for this Invoice.'}
            total_amount = sum(job.final_price or 0 for job in jobs)
            invoice.total_amount=total_amount
            db.session.commit()
            return job
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating job: {e}", exc_info=True)
            raise ServiceError("Could not update job. Please try again later.")


def safe_float(value, default=0.0):
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default

def safe_int(value, default=0):
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default

