"""
Centralized validation utilities for job data processing and password validation.
This module consolidates all validation logic to ensure consistency across endpoints.
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from backend.services.customer_service import CustomerService
from backend.services.driver_service import DriverService
from backend.services.vehicle_service import VehicleService
from backend.services.service_service import ServiceService


def validate_job_row(
    row_data: Dict[str, Any], 
    lookups: Dict[str, Any]
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Centralized validation function for job row data.
    
    Args:
        row_data: Dictionary containing the row data to validate
        lookups: Dictionary containing lookup data (customers, drivers, vehicles, services)
    
    Returns:
        Tuple of (is_valid, error_message, validated_data)
    """
    validated_data = row_data.copy()
    error_messages = []
    
    # Extract lookup data
    customers = lookups.get('customers', {})
    drivers = lookups.get('drivers', {})
    vehicles = lookups.get('vehicles', {})
    services = lookups.get('services', {})
    
    # Validate customer
    customer_value = row_data.get('customer', '').strip()
    
    if not customer_value:
        error_messages.append("Customer is required")
    elif customer_value not in customers:
        error_messages.append(f"Customer '{customer_value}' not found in database")
    else:
        validated_data['customer_id'] = customers[customer_value]
    
    # Validate driver
    driver_value = row_data.get('driver', '').strip()
    if driver_value and driver_value not in drivers:
        error_messages.append(f"Driver '{driver_value}' not found in database")
    elif driver_value:
        validated_data['driver_id'] = drivers[driver_value]
    
    # Validate vehicle
    vehicle_value = row_data.get('vehicle', '').strip()
    if vehicle_value and vehicle_value not in vehicles:
        error_messages.append(f"Vehicle '{vehicle_value}' not found in database")
    elif vehicle_value:
        validated_data['vehicle_id'] = vehicles[vehicle_value]
    
    # Validate service
    service_value = row_data.get('service', '').strip()
    
    if not service_value:
        error_messages.append("Service is required")
    elif service_value not in services:
        error_messages.append(f"Service '{service_value}' not found in database")
    else:
        validated_data['service_type'] = service_value  # Store service name
    
    # Validate required fields
    required_fields = [
        ('pickup_location', 'Pickup location'),
        ('dropoff_location', 'Dropoff location'),
        ('pickup_date', 'Pickup date'),
        ('pickup_time', 'Pickup time'),
        ('passenger_name', 'Passenger name'),
        # Removed 'passenger_mobile' from required fields to make it optional
    ]
    
    for field, field_name in required_fields:
        value = row_data.get(field, '').strip()
        if not value:
            error_messages.append(f"{field_name} is required")
    
    # Validate numeric fields
    numeric_fields = [
        ('base_price', 'Base price'),
        ('final_price', 'Final price'),
    ]
    
    for field, field_name in numeric_fields:
        value = row_data.get(field, '')
        if value:
            try:
                float_value = float(value)
                if float_value < 0:
                    error_messages.append(f"{field_name} cannot be negative")
                validated_data[field] = float_value
            except (ValueError, TypeError):
                error_messages.append(f"{field_name} must be a valid number")
    
    # Validate status field
    status_value = row_data.get('status', '').strip()
    if status_value:
        valid_statuses = ['new', 'pending', 'confirmed', 'otw', 'ots', 'pob', 'jc', 'sd', 'canceled']
        if status_value.lower() not in valid_statuses:
            error_messages.append(f"Status '{status_value}' is not valid. Must be one of: {', '.join(valid_statuses)}")
        else:
            validated_data['status'] = status_value.lower()
    else:
        # Set default status if not provided
        validated_data['status'] = 'new'
    
    # Validate additional dropoff locations and prices
    for i in range(1, 6):
        loc_field = f'dropoff_loc{i}'
        price_field = f'dropoff_loc{i}_price'
        
        loc_value = row_data.get(loc_field, '').strip()
        price_value = row_data.get(price_field, '')
        
        if loc_value and price_value:
            try:
                price_float = float(price_value)
                if price_float < 0:
                    error_messages.append(f"Dropoff location {i} price cannot be negative")
                validated_data[price_field] = price_float
            except (ValueError, TypeError):
                error_messages.append(f"Dropoff location {i} price must be a valid number")
    
    # Determine validation result
    is_valid = len(error_messages) == 0
    error_message = '; '.join(error_messages) if error_messages else ''
    
    return is_valid, error_message, validated_data


def get_validation_lookups() -> Dict[str, Any]:
    """
    Get all lookup data needed for validation.
    
    Returns:
        Dictionary containing customers, drivers, vehicles, and services
    """
    try:
        from backend.models.customer import Customer
        from backend.models.driver import Driver
        from backend.models.vehicle import Vehicle
        from backend.models.service import Service
        from backend.extensions import db
        
        # Get customers (active only)
        customers = Customer.query.filter_by(status='Active').all()
        customer_lookup = {customer.name: customer.id for customer in customers}
        
        # Get drivers (active only)
        drivers = Driver.query.filter_by(status='Active').all()
        driver_lookup = {driver.name: driver.id for driver in drivers}
        
        # Get vehicles (active only)
        vehicles = Vehicle.query.filter_by(status='Active').all()
        vehicle_lookup = {vehicle.number: vehicle.id for vehicle in vehicles}
        
        # Get services (active only)
        services = Service.query.filter_by(status='Active').all()
        service_lookup = {service.name: service.name for service in services}  # Keep name as key and value for compatibility
        
        # If no data found, try without status filter
        if not customer_lookup:
            customers = Customer.query.all()
            customer_lookup = {customer.name: customer.id for customer in customers}
            
        if not service_lookup:
            services = Service.query.all()
            service_lookup = {service.name: service.name for service in services}
        
        return {
            'customers': customer_lookup,
            'drivers': driver_lookup,
            'vehicles': vehicle_lookup,
            'services': service_lookup,
        }
    except Exception as e:
        # Return empty lookups if there's an error
        return {
            'customers': {},
            'drivers': {},
            'vehicles': {},
            'services': {},
        }


def validate_excel_data(
    excel_data: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """
    Validate entire Excel data and return processed results.
    
    Args:
        excel_data: List of dictionaries representing Excel rows
    
    Returns:
        Tuple of (processed_rows, error_count, lookups)
    """
    lookups = get_validation_lookups()
    processed_rows = []
    error_count = 0
    
    for row_data in excel_data:
        is_valid, error_message, validated_data = validate_job_row(row_data, lookups)
        
        validated_data['is_valid'] = is_valid
        validated_data['error_message'] = error_message
        
        if not is_valid:
            error_count += 1
        
        processed_rows.append(validated_data)
    
    return processed_rows, error_count, lookups 


# Password Validation Functions

def validate_password_strength(password: str) -> Tuple[bool, List[str]]:
    """
    Validate password strength based on complexity rules.
    
    Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    
    Args:
        password: The password to validate
        
    Returns:
        Tuple of (is_valid, list_of_error_messages)
    """
    if not password:
        return False, ['Password is required']
    
    errors = []
    
    # Check minimum length
    if len(password) < 8:
        errors.append('Password must be at least 8 characters long')
    
    # Check for uppercase letter
    if not re.search(r'[A-Z]', password):
        errors.append('Password must contain at least one uppercase letter')
    
    # Check for lowercase letter
    if not re.search(r'[a-z]', password):
        errors.append('Password must contain at least one lowercase letter')
    
    # Check for digit
    if not re.search(r'\d', password):
        errors.append('Password must contain at least one number')
    
    # Check for special character
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>\/?]', password):
        errors.append('Password must contain at least one special character (!@#$%^&*()_+-=[]{};\'":,.<>?/)')
    
    # Check for maximum length (security best practice)
    if len(password) > 128:
        errors.append('Password must not exceed 128 characters')
    
    return len(errors) == 0, errors


def validate_password_change_data(data: Dict[str, Any]) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Validate password change request data.
    
    Args:
        data: Dictionary containing current_password and new_password
        
    Returns:
        Tuple of (is_valid, dict_of_field_errors)
    """
    errors = {}
    
    # Validate current password
    current_password = data.get('current_password', '').strip()
    if not current_password:
        errors['current_password'] = ['Current password is required']
    
    # Validate new password
    new_password = data.get('new_password', '').strip()
    if not new_password:
        errors['new_password'] = ['New password is required']
    else:
        is_valid, password_errors = validate_password_strength(new_password)
        if not is_valid:
            errors['new_password'] = password_errors
        
        # Check if new password is different from current
        if current_password and new_password == current_password:
            if 'new_password' not in errors:
                errors['new_password'] = []
            errors['new_password'].append('New password must be different from current password')
    
    return len(errors) == 0, errors


def validate_password_reset_request_data(data: Dict[str, Any]) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Validate password reset request data.
    
    Args:
        data: Dictionary containing email
        
    Returns:
        Tuple of (is_valid, dict_of_field_errors)
    """
    errors = {}
    
    # Validate email
    email = data.get('email', '').strip().lower()
    if not email:
        errors['email'] = ['Email is required']
    else:
        # Basic email format validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            errors['email'] = ['Invalid email format']
    
    return len(errors) == 0, errors


def validate_password_reset_data(data: Dict[str, Any]) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Validate password reset data (with token).
    
    Args:
        data: Dictionary containing new_password and confirm_password
        
    Returns:
        Tuple of (is_valid, dict_of_field_errors)
    """
    errors = {}
    
    # Validate new password
    new_password = data.get('new_password', '').strip()
    if not new_password:
        errors['new_password'] = ['New password is required']
    else:
        is_valid, password_errors = validate_password_strength(new_password)
        if not is_valid:
            errors['new_password'] = password_errors
    
    # Validate confirm password
    confirm_password = data.get('confirm_password', '').strip()
    if not confirm_password:
        errors['confirm_password'] = ['Password confirmation is required']
    elif new_password and confirm_password != new_password:
        errors['confirm_password'] = ['Password confirmation does not match new password']
    
    return len(errors) == 0, errors