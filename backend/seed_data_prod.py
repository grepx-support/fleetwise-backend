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
            db.session.query(CustomerServicePricing).delete()
            db.session.query(SubCustomer).delete()
            db.session.query(Customer).delete()
            db.session.query(Vehicle).delete()
            db.session.query(VehicleType).delete()
            db.session.query(UserSettings).delete()
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
        admin = get_or_create(User, email='joseph@avant-garde.com.sg', defaults={
            'password': hash_password('joseph123'),
            'active': True,
            'fs_uniquifier': str(uuid.uuid4())
        })
        admin.roles.append(admin_role)

        db.session.commit()

        # --- Company Settings ---
        print("Creating company settings...")
        company_settings = {
                "general_settings": {
                    "company_name": "Avant-Garde Pte Ltd",
                    "company_address": "1 Rochor Canal Road,\n#03-11, Sim Lim Square,\nSingapore 188504",
                    "company_website": "https://avant-garde.com.sg",
                    "email_id": "support@avant-garde.com.sg",
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
        avant_garde = get_or_create(Customer, name='AG Internal',
                                   defaults={'email': 'support@avant-garde.com.sg', 'mobile': '91234567',
                                             'company_name': 'Avant-Garde Pte Ltd', 'status': 'Active'})
        
        # SubCustomers (departments)
        ag_ops = get_or_create(SubCustomer, name='Operations', customer_id=avant_garde.id)

        db.session.commit()

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

        print('\n--- Singapore Fleet Company Seed Data Complete ---')
        print(f'Users: {User.query.count()}')
        print(f'Roles: {Role.query.count()}')
        print(f'UserSettings: {UserSettings.query.count()}')
        print(f'Customers: {Customer.query.count()}')
        print(f'SubCustomers: {SubCustomer.query.count()}')
        print(f'VehicleTypes: {VehicleType.query.count()}')
        print(f'Services: {Service.query.count()}')
        print(f'ServicesVehicleTypePrice: {ServicesVehicleTypePrice.query.count()}')
        print(f'Contractors: {Contractor.query.count()}')
        print(f'ContractorServicePricing: {ContractorServicePricing.query.count()}')
        print(f'PostalCodes: {PostalCode.query.count()}')
        print('----------------------------------------')
        print('SUCCESS: Database seeded successfully!')


if __name__ == '__main__':
    main()
