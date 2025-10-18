# DISCLAIMER: THIS IS NOT REAL DATA. ALL CONTENT IN THIS FILE IS ENTIRELY FICTITIOUS AND INTENDED SOLELY FOR PROOF OF CONCEPT (POC) PURPOSES. ANY RESEMBLANCE TO REAL INDIVIDUALS OR ORGANIZATIONS IS PURELY COINCIDENTAL.
import os
import sys
import uuid
import csv
from datetime import datetime, timedelta
import random

# Add the parent directory to the Python path so we can import backend modules
# Get the project root directory dynamically
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from flask_security.utils import hash_password
from sqlalchemy import text
from sqlalchemy import select 

# Import models from the backend
try:
    from backend.server import app, db
    from backend.models.user import User
    from backend.models.role import Role
    from backend.models.customer import Customer
    from backend.models.sub_customer import SubCustomer
    from backend.models.vehicle import Vehicle
    from backend.models.vehicle_type import VehicleType
    from backend.models.driver import Driver
    from backend.models.job import Job
    from backend.models.invoice import Invoice, Payment
    from backend.models.customer_service_pricing import CustomerServicePricing
    from backend.models.driver_commission_table import DriverCommissionTable
    from backend.models.service import Service
    from backend.models.settings import UserSettings
    from backend.models.postal_code import PostalCode
    from backend.models.contractor import Contractor
    from backend.models.contractor_service_pricing import ContractorServicePricing
    from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice
except ImportError as e:
    print(f"ERROR: Could not import backend modules: {e}")
    print("Make sure you're running this from the correct directory and that backend modules exist.")
    sys.exit(1)


# Helper: get or create
def get_or_create(model, defaults=None, **kwargs):
    instance = model.query.filter_by(**kwargs).first()
    if instance:
        return instance
    params = dict(kwargs)
    if defaults:
        params.update(defaults)
    instance = model(**params)
    db.session.add(instance)
    db.session.commit()
    return instance


def seed_postal_codes():
    """Import postal codes from CSV file into database"""
    print("Importing postal codes from CSV...")
    
    # Path to the CSV file
    csv_path = os.path.join(current_dir, 'sg_zipcode_mapper.csv')
    
    if not os.path.exists(csv_path):
        print(f"WARNING: CSV file not found at {csv_path}")
        return
    
    # Clear existing postal codes
    try:
        db.session.query(PostalCode).delete()
        db.session.commit()
        print("Cleared existing postal codes")
    except Exception as e:
        print(f"Warning: Could not clear existing postal codes: {e}")
        db.session.rollback()
    
    try:
        postal_codes_added = 0
        batch_size = 1000  # Process in batches for better performance
        postal_codes_batch = []
        
        # Try different encodings
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        file_opened = False
        
        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding) as file:
                    csv_reader = csv.reader(file)
                    
                    print(f"Reading CSV with {encoding} encoding")
                    seen_postal_codes = set()  # Track duplicates within the file
                    
                    for row_num, row in enumerate(csv_reader, 1):
                        if len(row) < 9:  # Ensure we have enough columns
                            continue
                            
                        try:
                            # Extract postal code and address from CSV
                            # Based on CSV structure: postal,latitude,longitude,searchval,blk_no,road_name,building,address,postal
                            postal_code = row[0].strip()  # First column
                            address = row[7].strip()      # Address column (8th column, index 7)
                            
                            # Skip if postal code or address is empty
                            if not postal_code or not address:
                                continue
                            
                            # Validate postal code (Singapore postal codes are 6 digits)
                            if not postal_code.isdigit() or len(postal_code) != 6:
                                continue
                            
                            # Skip duplicates within the file (keep first occurrence)
                            if postal_code in seen_postal_codes:
                                continue
                            
                            seen_postal_codes.add(postal_code)
                            
                            # Create PostalCode object
                            postal_code_obj = PostalCode(
                                postal_code=postal_code,
                                address=address
                            )
                            
                            postal_codes_batch.append(postal_code_obj)
                            
                            # Process batch when it reaches batch_size
                            if len(postal_codes_batch) >= batch_size:
                                db.session.bulk_save_objects(postal_codes_batch)
                                db.session.commit()
                                postal_codes_added += len(postal_codes_batch)
                                print(f"Processed {postal_codes_added} postal codes...")
                                postal_codes_batch = []
                                
                        except Exception as e:
                            print(f"Error processing row {row_num}: {e}")
                            continue
                    
                    # Process remaining batch
                    if postal_codes_batch:
                        db.session.bulk_save_objects(postal_codes_batch)
                        db.session.commit()
                        postal_codes_added += len(postal_codes_batch)
                    
                    file_opened = True
                    break
                    
            except UnicodeDecodeError:
                print(f"Failed to read with {encoding} encoding, trying next...")
                continue
            except Exception as e:
                print(f"Error with {encoding}: {e}")
                continue
        
        if not file_opened:
            print("ERROR: Could not read the file with any encoding")
            return
        
        print(f"Successfully imported {postal_codes_added} unique postal codes from CSV")
        
    except Exception as e:
        print(f"Error importing postal codes: {e}")
        db.session.rollback()


def main():
    print("Starting database seeding...")

    with app.app_context():
        # Create all tables first
        print("Creating database tables...")
        db.create_all()

        # Wipe all data in the correct order to avoid FK issues
        print("Clearing existing data...")
        try:
            db.session.query(Job).delete()
            db.session.query(Invoice).delete()
            db.session.query(CustomerServicePricing).delete()
            db.session.query(DriverCommissionTable).delete()
            db.session.query(SubCustomer).delete()
            db.session.query(Customer).delete()
            db.session.query(Vehicle).delete()
            db.session.query(VehicleType).delete()
            db.session.query(Driver).delete()
            db.session.query(UserSettings).delete()
            db.session.execute(text('DELETE FROM roles_users'))
            db.session.query(User).delete()
            db.session.query(Role).delete()
            db.session.commit()
            print("Existing data cleared successfully")
        except Exception as e:
            print(f"Warning: Could not clear existing data: {e}")
            db.session.rollback()

        # --- Import Postal Codes ---
        seed_postal_codes()

        # --- Roles ---
        print("Creating roles...")
        admin_role = get_or_create(Role, name='admin', defaults={'description': 'System Administrator'})
        manager_role = get_or_create(Role, name='manager', defaults={'description': 'Fleet Manager'})
        driver_role = get_or_create(Role, name='driver', defaults={'description': 'Driver'})
        customer_role = get_or_create(Role, name='customer', defaults={'description': 'Customer'})
        accountant_role = get_or_create(Role, name='accountant', defaults={'description': 'Accountant'})

        # --- Vehicle Types ---
        print("Creating vehicle types...")
        sedan_type = get_or_create(VehicleType, name='E-Class Sedan', defaults={
            'description': 'E-Class Sedan type vehicle transfers',
            'status': True
        })
        prem6_type = get_or_create(VehicleType, name='Premium 6 Seater', defaults={
            'description': 'Premium 6 Seater type vehicle transfers',
            'status': True
        })
        vclass7_type = get_or_create(VehicleType, name='V-Class (7 Seater)', defaults={
            'description': 'V-Class (7 Seater) type vehicle transfers',
            'status': True
        })
        coach13_type = get_or_create(VehicleType, name='COACH (13 Seater)', defaults={
            'description': 'COACH (13 Seater) type vehicle transfers',
            'status': True
        })
        coach23_type = get_or_create(VehicleType, name='COACH (23 Seater)', defaults={
            'description': 'COACH (23 Seater) type vehicle transfers',
            'status': True
        })
        coach45_type = get_or_create(VehicleType, name='COACH (45 Seater)', defaults={
            'description': 'COACH (45 Seater) type vehicle transfers',
            'status': True
        })

        # --- Users ---
        print("Creating users...")
        admin = get_or_create(User, email='admin@grepx.sg', defaults={
            'password': hash_password('adminpass'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        admin.roles.append(admin_role)

        manager = get_or_create(User, email='manager@grepx.sg', defaults={
            'password': hash_password('managerpass'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        manager.roles.append(manager_role)

        support = get_or_create(User, email='support@grepx.sg', defaults={
            'password': hash_password('supportpass'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        support.roles.append(accountant_role)

        # Driver users (linked to driver entity later)
        driver_user1 = get_or_create(User, email='john.tan@grepx.sg', defaults={
            'password': hash_password('driverpass1'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        driver_user1.roles.append(driver_role)

        driver_user2 = get_or_create(User, email='susan.ong@grepx.sg', defaults={
            'password': hash_password('driverpass2'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        driver_user2.roles.append(driver_role)

        # Customer user
        customer_user = get_or_create(User, email='customer@grepx.sg', defaults={
            'password': hash_password('customerpass'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        customer_user.roles.append(customer_role)

        # Will Smith test user
        will_smith_user = get_or_create(User, email='willsmith80877@gmail.com', defaults={
            'password': hash_password('pass@123'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        will_smith_user.roles.append(customer_role)

        db.session.commit()

        # --- Company Settings ---
        print("Creating company settings...")
        company_settings = {
                "general_settings": {
                    "company_name": "Avant-Garde Pte Ltd",
                    "company_address": "1 Rochor Canal Road,\n#03-11, Sim Lim Square,\nSingapore 188504",
                    "company_website": "https://avantgarde.sg",
                    "email_id": "support@avantgarde.sg",
                    "contact_number": "+65 6532 1234",
                    "dark_mode": True,
                    "language": "en",
                    "timezone": "SGT"
                },
                "photo_config": {
                    "allowed_formats": "jpg,png",
                    "max_photos": 2,
                    "max_size_mb": 1,
                    "stage": "OTS"
                },
                "billing_settings": {
                    "company_logo": "/static/uploads/comp_logo_compressed.jpg",
                    "billing_payment_info": "Kindly arrange all cheques to be made payable to \"Avant-Garde Services Pte Ltd\" and crossed \"A/C Payee Only\".\nAlternatively, for Bank Transfer / Electronic Payment please find our bank details as follows:\nUOB Bank (7375) :  Current A/C : 3733169263 \nBank Swift Code : UOVBSGSG\nCorporate Paynow : 201017519Z",
                    "billing_qr_code_image": "/static/uploads/grepx_qr_compressed.jpg"
                }
            }
        
        # Create company settings for admin user
        admin_settings = get_or_create(UserSettings, user_id=admin.id, defaults={'preferences': company_settings})

        # --- Customers & SubCustomers ---
        print("Creating customers and sub-customers...")
        grepx_tech = get_or_create(Customer, name='GrepX Technologies',
                                   defaults={'email': 'info@grepx.sg', 'mobile': '91234567',
                                             'company_name': 'GrepX Technologies', 'status': 'Active'})
        abc = get_or_create(Customer, name='ABC Technologies',
                            defaults={'email': 'contact@abc.sg', 'mobile': '92345678',
                                      'company_name': 'ABC Technologies', 'status': 'Active'})
        beta_univ = get_or_create(Customer, name='Beta University',
                                  defaults={'email': 'admin@betauniv.sg', 'mobile': '93456789',
                                            'company_name': 'Beta University', 'status': 'Active'})
        zenith = get_or_create(Customer, name='Zenith Solutions',
                               defaults={'email': 'info@zenith.sg', 'mobile': '95551234',
                                         'company_name': 'Zenith Solutions', 'status': 'Active'})
        orbitron = get_or_create(Customer, name='Orbitron Dynamics',
                                 defaults={'email': 'contact@orbitron.sg', 'mobile': '95554321',
                                           'company_name': 'Orbitron Dynamics', 'status': 'Active'})
        
        # SubCustomers (departments)
        grepx_ops = get_or_create(SubCustomer, name='Operations', customer_id=grepx_tech.id)
        grepx_hr = get_or_create(SubCustomer, name='HR', customer_id=grepx_tech.id)
        abc_it = get_or_create(SubCustomer, name='IT', customer_id=abc.id)
        beta_admin = get_or_create(SubCustomer, name='Admin', customer_id=beta_univ.id)
        zenith_ops = get_or_create(SubCustomer, name='Operations', customer_id=zenith.id)
        zenith_hr = get_or_create(SubCustomer, name='HR', customer_id=zenith.id)
        orbitron_fac = get_or_create(SubCustomer, name='Facilities', customer_id=orbitron.id)
        orbitron_fin = get_or_create(SubCustomer, name='Finance', customer_id=orbitron.id)

        # --- Vehicles ---
        print("Creating vehicles...")
        vehicle1 = get_or_create(Vehicle, number='SGA1234X',
                                 defaults={'name': 'Toyota Hiace', 'type': '13-Seater', 'status': 'Active'})
        vehicle2 = get_or_create(Vehicle, number='SGD5678Y',
                                 defaults={'name': 'Mercedes Sprinter', 'type': '23-Seater', 'status': 'Active'})
        vehicle3 = get_or_create(Vehicle, number='SGL9999Z',
                                 defaults={'name': 'Lexus LM', 'type': 'Luxury', 'status': 'Active'})

        # --- Drivers ---
        print("Creating drivers...")
        driver1 = get_or_create(Driver, name='John Tan', defaults={'email': 'john.tan@grepx.sg', 'mobile': '91234567',
                                                                   'license_number': 'S1234567A',
                                                                   'vehicle_id': vehicle1.id, 'status': 'Active'})
        driver2 = get_or_create(Driver, name='Susan Ong', defaults={'email': 'susan.ong@grepx.sg', 'mobile': '98765432',
                                                                    'license_number': 'S7654321B',
                                                                    'vehicle_id': vehicle2.id, 'status': 'Active'})
        # Link driver users
        driver_user1.driver_id = driver1.id
        driver_user2.driver_id = driver2.id
        db.session.commit()

        # --- Driver Commission Tables ---
        print("Creating driver commission tables...")
        get_or_create(DriverCommissionTable, driver_id=driver1.id, job_type='Airport Transfer',
                      vehicle_type='13-Seater', defaults={'commission_amount': 15.0})
        get_or_create(DriverCommissionTable, driver_id=driver2.id, job_type='Corporate Charter',
                      vehicle_type='23-Seater', defaults={'commission_amount': 30.0})

        passenger_names = [
            'Sarah Johnson', 'Michael Chen', 'Emily Rodriguez', 'David Kumar', 'Lisa Wang',
            'James Thompson', 'Maria Garcia', 'Ahmed Hassan', 'Jennifer Lee', 'Robert Smith',
            'Priya Patel', 'Christopher Brown', 'Anna Kowalski', 'Mohammed Ali', 'Sophie Martin'
        ]

        # --- Jobs ---
        print("Creating initial jobs...")
        today = datetime.now().date()
        job1 = get_or_create(Job, customer_id=grepx_tech.id, sub_customer_id=grepx_ops.id, driver_id=driver1.id,
                             vehicle_id=vehicle1.id, service_type='Airport Transfer - Arrival ', pickup_location='Alpha Airport',
                             dropoff_location='Orchard Hotel', pickup_date=str(today), pickup_time='10:00', status='jc',
                             base_price=60.0, final_price=80.0, driver_commission=15.0, penalty=0.0, passenger_name=random.choice(passenger_names))
        job2 = get_or_create(Job, customer_id=abc.id, sub_customer_id=abc_it.id, driver_id=driver2.id,
                             vehicle_id=vehicle2.id, service_type='Airport Transfer - Departure', pickup_location='ABC Tower',
                             dropoff_location='Jurong East', pickup_date=str(today + timedelta(days=1)),
                             pickup_time='14:00', status='jc', base_price=120.0, final_price=150.0,
                             driver_commission=30.0, penalty=0.0, passenger_name=random.choice(passenger_names))
        job3 = get_or_create(Job, customer_id=beta_univ.id, sub_customer_id=beta_admin.id, driver_id=driver1.id,
                             vehicle_id=vehicle3.id, service_type='City / Short Transfer', pickup_location='Beta University',
                             dropoff_location='Marina Bay Sands', pickup_date=str(today + timedelta(days=2)),
                             pickup_time='18:00', status='canceled', base_price=200.0, final_price=0.0,
                             driver_commission=0.0, penalty=50.0, passenger_name=random.choice(passenger_names))

        # --- Invoices ---
        print("Creating invoices...")
        invoice1 = get_or_create(Invoice, customer_id=grepx_tech.id,
                                 defaults={'date': today, 'status': 'Paid', 'total_amount': 80.0,
                                           'file_path': 'invoice_2_20250730101341.pdf'})
        invoice2 = get_or_create(Invoice, customer_id=abc.id,
                                 defaults={'date': today + timedelta(days=1), 'status': 'Unpaid', 'total_amount': 150.0,
                                           'file_path': 'invoice_2_20250730101341.pdf'})
        
        # Create payment entry for invoice1
        payment1 = get_or_create(Payment, invoice_id=invoice1.id,
                                 defaults={'amount': 80.0, 'date': today, 'reference_number': 'PAY-001-2024',
                                           'notes': 'Full payment received via bank transfer'})
        
        # Link jobs to invoices
        job1.invoice_id = invoice1.id
        job2.invoice_id = invoice2.id

        db.session.commit()

        invoice3 = get_or_create(Invoice, customer_id=zenith.id,
                                 defaults={'date': today + timedelta(days=1), 'status': 'Unpaid', 'total_amount': 1200.0,
                                           'file_path': 'invoice_3_20250730101341.pdf'})

        # Create 15 additional jobs in a loop
        print("Creating 15 additional jobs...")
        # Define arrays for varied job data
        drivers = [driver1, driver2]
        vehicles = [vehicle1, vehicle2, vehicle3]
        service_types = ['Airport Transfer - Arrival', 'Airport Transfer - Departure', 'City / Short Transfer', 'Outside City Transfer', 'Student Trip', 'Worker Trip', 'Cross Border Transfer', 'Tour Package - 4Hrs', 'Tour Package - 8Hrs', 'Tour Package - 10Hrs']
        pickup_locations = ['ABC Tower', 'Alpha Airport', 'Beta University', 'Marina Bay Sands', 'Orchard Hotel', 'Raffles Place', 'Jurong East', 'Changi Airport', 'Sentosa', 'Clarke Quay']
        dropoff_locations = ['Jurong East', 'Orchard Hotel', 'Marina Bay Sands', 'Alpha Airport', 'Raffles Place', 'Beta University', 'Changi Airport', 'Sentosa', 'Clarke Quay', 'ABC Tower']
        times = ['08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00']
        
        # Create jobs 3-17 (15 jobs total)
        for i in range(3, 18):  # Creates jobs 3 through 17
            # Use modulo to cycle through arrays
            driver = drivers[i % len(drivers)]
            vehicle = vehicles[i % len(vehicles)]
            service_type = service_types[i % len(service_types)]
            pickup_location = pickup_locations[i % len(pickup_locations)]
            dropoff_location = dropoff_locations[i % len(dropoff_locations)]
            time = times[i % len(times)]
            passenger_name = passenger_names[i-3]  # Get passenger name (i-3 because loop starts at 3)
            
            # Vary the date (spread over next 30 days)
            job_date = today + timedelta(days=(i % 30) + 1)
            
            job = get_or_create(Job, 
                               customer_id=zenith.id, 
                               sub_customer_id=zenith_hr.id, 
                               driver_id=driver.id,
                               vehicle_id=vehicle.id, 
                               service_type=service_type, 
                               pickup_location=pickup_location,
                               dropoff_location=dropoff_location, 
                               pickup_date=str(job_date),
                               pickup_time=time, 
                               status='jc', 
                               base_price=60.0, 
                               final_price=80.0,
                               driver_commission=0.0, 
                               penalty=0.0,
                               passenger_name=passenger_name)
            # Link job to invoice
            job.invoice_id = invoice3.id
            
            print(f"Created job {i}: {service_type} from {pickup_location} to {dropoff_location} on {job_date}")

        db.session.commit()

        # --- Additional Vehicles ---
        print("Creating additional vehicles...")
        vehicle4 = get_or_create(Vehicle, number='SGP8888A',
                                 defaults={'name': 'Hyundai Staria', 'type': '13-Seater', 'status': 'Active'})
        vehicle5 = get_or_create(Vehicle, number='SGQ7777B',
                                 defaults={'name': 'Ford Transit', 'type': '23-Seater', 'status': 'Inactive'})
        vehicle6 = get_or_create(Vehicle, number='SGR6666C',
                                 defaults={'name': 'Toyota Alphard', 'type': 'Luxury', 'status': 'Active'})

        # --- Additional Drivers ---
        print("Creating additional drivers...")
        driver3 = get_or_create(Driver, name='David Lee', defaults={'email': 'david.lee@grepx.sg', 'mobile': '91112222',
                                                                    'license_number': 'S2345678C',
                                                                    'vehicle_id': vehicle4.id, 'status': 'Active'})
        driver4 = get_or_create(Driver, name='Rachel Goh',
                                defaults={'email': 'rachel.goh@grepx.sg', 'mobile': '92223333',
                                          'license_number': 'S3456789D', 'vehicle_id': vehicle5.id, 'status': 'Active'})
        driver5 = get_or_create(Driver, name='Pei Fen Chua',
                                defaults={'email': 'pei.fen.chua@grepx.sg', 'mobile': '93334444',
                                          'license_number': 'S4567890E', 'vehicle_id': vehicle6.id, 'status': 'Active'})

        db.session.commit()

        # --- Expanded Driver Commission Tables ---
        print("Creating expanded commission tables...")
        for drv, jtype, vtype, comm in [
            (driver1, 'Airport Transfer', '13-Seater', 15),
            (driver2, 'Corporate Charter', '23-Seater', 30),
            (driver3, 'Staff Shuttle', '13-Seater', 18),
            (driver4, 'Event Charter', '23-Seater', 32),
            (driver5, 'VIP Charter', 'Luxury', 40),
            (driver1, 'VIP Charter', 'Luxury', 38),
            (driver2, 'Airport Transfer', '13-Seater', 16),
        ]:
            get_or_create(DriverCommissionTable, driver_id=drv.id, job_type=jtype, vehicle_type=vtype,
                          defaults={'commission_amount': comm})

        # --- Services ---
        print("Creating services...")
        airTrsArr = get_or_create(Service, name='Airport Transfer - Arrival',
                      defaults={'description': 'Airport Transfer - Arrival ', 'status': 'Active'})
        airTraDep = get_or_create(Service, name='Airport Transfer - Departure',
                      defaults={'description': 'Airport Transfer - Departure', 'status': 'Active'})
        cityShortTrs = get_or_create(Service, name='City / Short Transfer',
                      defaults={'description': 'City / Short Transfer', 'status': 'Active'})
        outCityTrs = get_or_create(Service, name='Outside City Transfer',
                      defaults={'description': 'Outside City Transfer', 'status': 'Active'})
        studentTrip = get_or_create(Service, name='Student Trip',
                      defaults={'description': 'Student Trip', 'status': 'Active'})
        workerTrip = get_or_create(Service, name='Worker Trip',
                      defaults={'description': 'Worker Trip', 'status': 'Active'})
        crossBorderTrs = get_or_create(Service, name='Cross Border Transfer',
                      defaults={'description': 'Cross Border Transfer', 'status': 'Active'})
        tour4Hrs = get_or_create(Service, name='Tour Package - 4Hrs',
                      defaults={'description': 'Tour Package - 4Hrs', 'status': 'Active'})
        tour8Hrs = get_or_create(Service, name='Tour Package - 8Hrs',
                      defaults={'description': 'Tour Package - 8Hrs', 'status': 'Active'})
        tour10Hrs = get_or_create(Service, name='Tour Package - 10Hrs',
                      defaults={'description': 'Tour Package - 10Hrs', 'status': 'Active'})

        # --- Contractors ---
        print("Creating contractors...")
        # Create the default "AG (Internal)" contractor
        ag_internal_contractor = get_or_create(Contractor, name='AG (Internal)',
                                               defaults={'status': 'Active'})
        
        # Update all existing jobs to associate with the default contractor
        print("Updating existing jobs to associate with default contractor...")
        Job.query.update({Job.contractor_id: ag_internal_contractor.id})
        db.session.commit()

        # Create contractor service pricing entries for AG (Internal)
        print("Creating contractor service pricing for AG (Internal)...")
        services = Service.query.all()
        
        # Define realistic cost pricing for AG (Internal) contractor
        # These costs represent what AG charges for each service
        service_costs = {
            'Airport Transfer - Arrival': 17.0,
            'Airport Transfer - Departure': 15.0,
            'City / Short Transfer': 10.0,
            'Outside City Transfer': 14.0,
            'Student Trip': 20.0,
            'Worker Trip': 25.0,
            'Cross Border Transfer': 40.0,
            'Tour Package - 4Hrs': 22.0,
            'Tour Package - 8Hrs': 34.0,
            'Tour Package - 10Hrs': 48.0
        }
        
        for service in services:
            # Use the defined cost or default to 0.0 if service not in mapping
            cost = service_costs.get(service.name, 0.0)
            get_or_create(ContractorServicePricing, 
                         contractor_id=ag_internal_contractor.id,
                         service_id=service.id,
                         defaults={'cost': cost})

        db.session.commit()

        # --- Services Vehicle Type Pricing (Default Pricing) ---
        print("Creating default service vehicle type pricing...")
        
        # Load all services and vehicle types
        services = Service.query.order_by(Service.id).all()
        vehicle_types = VehicleType.query.order_by(VehicleType.id).all()
        
        # Define default pricing for each service-vehicle type combination
        # These are the base prices that will be used as defaults for customer pricing
        default_pricing = {
            # Service Name -> Vehicle Type -> Price
            'Airport Transfer - Arrival': {
                'E-Class Sedan': 65.0,
                'Premium 6 Seater': 75.0,
                'V-Class (7 Seater)': 85.0,
                'COACH (13 Seater)': 120.0,
                'COACH (23 Seater)': 180.0,
                'COACH (45 Seater)': 250.0
            },
            'Airport Transfer - Departure': {
                'E-Class Sedan': 70.0,
                'Premium 6 Seater': 80.0,
                'V-Class (7 Seater)': 90.0,
                'COACH (13 Seater)': 130.0,
                'COACH (23 Seater)': 190.0,
                'COACH (45 Seater)': 260.0
            },
            'City / Short Transfer': {
                'E-Class Sedan': 50.0,
                'Premium 6 Seater': 60.0,
                'V-Class (7 Seater)': 70.0,
                'COACH (13 Seater)': 100.0,
                'COACH (23 Seater)': 150.0,
                'COACH (45 Seater)': 200.0
            },
            'Outside City Transfer': {
                'E-Class Sedan': 80.0,
                'Premium 6 Seater': 90.0,
                'V-Class (7 Seater)': 100.0,
                'COACH (13 Seater)': 140.0,
                'COACH (23 Seater)': 200.0,
                'COACH (45 Seater)': 280.0
            },
            'Student Trip': {
                'E-Class Sedan': 100.0,
                'Premium 6 Seater': 120.0,
                'V-Class (7 Seater)': 140.0,
                'COACH (13 Seater)': 200.0,
                'COACH (23 Seater)': 300.0,
                'COACH (45 Seater)': 400.0
            },
            'Worker Trip': {
                'E-Class Sedan': 120.0,
                'Premium 6 Seater': 140.0,
                'V-Class (7 Seater)': 160.0,
                'COACH (13 Seater)': 220.0,
                'COACH (23 Seater)': 320.0,
                'COACH (45 Seater)': 450.0
            },
            'Cross Border Transfer': {
                'E-Class Sedan': 150.0,
                'Premium 6 Seater': 170.0,
                'V-Class (7 Seater)': 190.0,
                'COACH (13 Seater)': 250.0,
                'COACH (23 Seater)': 350.0,
                'COACH (45 Seater)': 500.0
            },
            'Tour Package - 4Hrs': {
                'E-Class Sedan': 200.0,
                'Premium 6 Seater': 250.0,
                'V-Class (7 Seater)': 300.0,
                'COACH (13 Seater)': 400.0,
                'COACH (23 Seater)': 600.0,
                'COACH (45 Seater)': 800.0
            },
            'Tour Package - 8Hrs': {
                'E-Class Sedan': 350.0,
                'Premium 6 Seater': 450.0,
                'V-Class (7 Seater)': 550.0,
                'COACH (13 Seater)': 700.0,
                'COACH (23 Seater)': 1000.0,
                'COACH (45 Seater)': 1400.0
            },
            'Tour Package - 10Hrs': {
                'E-Class Sedan': 450.0,
                'Premium 6 Seater': 550.0,
                'V-Class (7 Seater)': 650.0,
                'COACH (13 Seater)': 850.0,
                'COACH (23 Seater)': 1200.0,
                'COACH (45 Seater)': 1700.0
            }
        }
        
        # Create ServicesVehicleTypePrice entries
        for service in services:
            for vehicle_type in vehicle_types:
                service_pricing = default_pricing.get(service.name, {})
                price = service_pricing.get(vehicle_type.name, 50.0)  # Default price if not found
                
                get_or_create(ServicesVehicleTypePrice,
                             service_id=service.id,
                             vehicle_type_id=vehicle_type.id,
                             defaults={'price': price})
        
        db.session.commit()

        # --- Customer Service Pricing Tables ---
        print("Creating customer service pricing tables...")

        # Customer pricing data: (customer, service_object, vehicle_type, price)
        customers = [grepx_tech, abc, beta_univ, zenith, orbitron]

        # Load all services, vehicle types, and default prices once
        services = Service.query.order_by(Service.id).all()
        vehicle_types = VehicleType.query.order_by(VehicleType.id).all()

        defaults_rows = db.session.execute(
         select(
        ServicesVehicleTypePrice.service_id,
        ServicesVehicleTypePrice.vehicle_type_id,
        ServicesVehicleTypePrice.price,
        )
        ).all()
        defaults_map = {(s_id, vt_id): (float(price) if price is not None else None)
                for (s_id, vt_id, price) in defaults_rows}

        # Helper to upsert one row (your get_or_create matches unique keys via kwargs)
        def seed_csp(cust_id: int, service_id: int, vehicle_type_id: int, price):
            get_or_create(
        CustomerServicePricing,
        cust_id=cust_id,
        service_id=service_id,
        vehicle_type_id=vehicle_type_id,
        defaults={"price": price},
    )

        #    Create rows: for every customer × (service × vehicle_type)
        for cust in customers:
            for svc in services:
                for vt in vehicle_types:
                    price = defaults_map.get((svc.id, vt.id))
                    # If you want sparse table, skip None defaults:
                    if price is None:
                        continue
                    seed_csp(cust.id, svc.id, vt.id, price)
        db.session.commit()

        # --- Jobs for All Statuses, Past & Future ---
        print("Creating comprehensive job data...")
        job_statuses = ['new', 'pending', 'confirmed', 'otw', 'ots', 'pob', 'jc', 'sd', 'canceled']
        job_customers = [grepx_tech, abc, beta_univ, zenith, orbitron]
        job_subcustomers = [grepx_ops, grepx_hr, abc_it, beta_admin, zenith_ops, zenith_hr, orbitron_fac, orbitron_fin]
        job_drivers = [driver1, driver2, driver3, driver4, driver5]
        job_vehicles = [vehicle1, vehicle2, vehicle3, vehicle4, vehicle5, vehicle6]
        job_services = ['Airport Transfer - Arrival ', 'Airport Transfer - Departure', 'City / Short Transfer', 'Outside City Transfer', 'Student Trip', 'Worker Trip', 'Cross Border Transfer', 'Tour Package - 4Hrs', 'Tour Package - 8Hrs', 'Tour Package - 10Hrs']
        today = datetime.now().date()
        job_counter = 0
        passenger_name = random.choice(passenger_names)

        for i, status in enumerate(job_statuses):
            # Past jobs (10 days ago to 1 day ago)
            for days_ago in range(10, 0, -2):
                job_counter += 1
                cust = job_customers[job_counter % len(job_customers)]
                subcust = job_subcustomers[job_counter % len(job_subcustomers)]
                drv = job_drivers[job_counter % len(job_drivers)]
                veh = job_vehicles[job_counter % len(job_vehicles)]
                svc = job_services[job_counter % len(job_services)]
                base = 60 + (job_counter % 5) * 10
                final = base + 20 if status != 'canceled' else 0
                penalty = 0 if status != 'canceled' else 30 + (job_counter % 3) * 10
                get_or_create(Job, customer_id=cust.id, sub_customer_id=subcust.id, driver_id=drv.id, vehicle_id=veh.id,
                              service_type=svc, pickup_location='Alpha Airport', dropoff_location='Orchard Hotel',
                              pickup_date=str(today - timedelta(days=days_ago)), pickup_time='09:00', status=status,
                              base_price=base, final_price=final, driver_commission=15.0, penalty=penalty, passenger_name=passenger_name)

            # Future jobs (1 to 10 days ahead)
            for days_ahead in range(1, 11, 2):
                job_counter += 1
                cust = job_customers[job_counter % len(job_customers)]
                subcust = job_subcustomers[job_counter % len(job_subcustomers)]
                drv = job_drivers[job_counter % len(job_drivers)]
                veh = job_vehicles[job_counter % len(job_vehicles)]
                svc = job_services[job_counter % len(job_services)]
                base = 60 + (job_counter % 5) * 10
                final = base + 20 if status != 'canceled' else 0
                penalty = 0 if status != 'canceled' else 30 + (job_counter % 3) * 10
                get_or_create(Job, customer_id=cust.id, sub_customer_id=subcust.id, driver_id=drv.id, vehicle_id=veh.id,
                              service_type=svc, pickup_location='Raffles Place', dropoff_location='Jurong East',
                              pickup_date=str(today + timedelta(days=days_ahead)), pickup_time='15:00', status=status,
                              base_price=base, final_price=final, driver_commission=15.0, penalty=penalty, passenger_name=passenger_name)

        db.session.commit()

        # --- Ensure at least one job in the next hour for dashboard timeline ---
        print("Creating timeline job...")
        now = datetime.now()
        next_hour = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        job_for_timeline = get_or_create(
            Job,
            customer_id=grepx_tech.id,
            sub_customer_id=grepx_ops.id,
            driver_id=driver1.id,
            vehicle_id=vehicle1.id,
            service_type='Airport Transfer - Departure',
            pickup_location='Alpha Airport',
            dropoff_location='Orchard Hotel',
            pickup_date=str(now.date()),
            pickup_time=next_hour.strftime('%H:%M'),
            status='pending',
            base_price=60.0,
            final_price=80.0,
            driver_commission=15.0,
            penalty=0.0
        )
        db.session.commit()

        print('\n--- Singapore Fleet Company Seed Data Complete ---')
        print(f'Users: {User.query.count()}')
        print(f'Roles: {Role.query.count()}')
        print(f'UserSettings: {UserSettings.query.count()}')
        print(f'Customers: {Customer.query.count()}')
        print(f'SubCustomers: {SubCustomer.query.count()}')
        print(f'VehicleTypes: {VehicleType.query.count()}')
        print(f'Vehicles: {Vehicle.query.count()}')
        print(f'Drivers: {Driver.query.count()}')
        print(f'Jobs: {Job.query.count()}')
        print(f'Invoices: {Invoice.query.count()}')
        print(f'CustomerServicePricing: {CustomerServicePricing.query.count()}')
        print(f'DriverCommissionTables: {DriverCommissionTable.query.count()}')
        print(f'Services: {Service.query.count()}')
        print(f'ServicesVehicleTypePrice: {ServicesVehicleTypePrice.query.count()}')
        print(f'Contractors: {Contractor.query.count()}')
        print(f'ContractorServicePricing: {ContractorServicePricing.query.count()}')
        print(f'PostalCodes: {PostalCode.query.count()}')
        print('----------------------------------------')
        print('SUCCESS: Database seeded successfully!')


if __name__ == '__main__':
    main()
