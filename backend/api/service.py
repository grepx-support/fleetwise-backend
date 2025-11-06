from flask import Blueprint, request, jsonify
from backend.services.service_service import ServiceService, ServiceError
from backend.schemas.service_schema import ServiceSchema
import logging
import json
import re
from flask_security.decorators import roles_required, roles_accepted, auth_required
from backend.extensions import db
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import IntegrityError

service_bp = Blueprint('service', __name__)
schema = ServiceSchema(session=db.session)
schema_many = ServiceSchema(many=True, session=db.session)

def handle_service_error(se):
    """Centralized ServiceError handling with appropriate HTTP status codes."""
    if "already exists" in se.message.lower():
        return jsonify({'error': se.message}), 409
    return jsonify({'error': se.message}), 400


def validate_condition_config(condition_type, condition_config_str):
    """
    Validate condition_config JSON matches condition_type schema.

    Args:
        condition_type: The type of condition ('always', 'time_range', 'additional_stops')
        condition_config_str: JSON string of the configuration

    Raises:
        ValueError: If validation fails with specific error message
    """
    # If no condition_type, config should be empty
    if not condition_type or condition_type == 'always':
        if condition_config_str:
            raise ValueError("condition_config should be empty for 'always' or no condition_type")
        return

    # For other condition types, config is required
    if not condition_config_str:
        raise ValueError(f"condition_config is required for condition_type '{condition_type}'")

    # Validate JSON structure
    try:
        config = json.loads(condition_config_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in condition_config: {str(e)}")

    if not isinstance(config, dict):
        raise ValueError("condition_config must be a JSON object")

    # Validate based on condition_type
    if condition_type == 'time_range':
        required_fields = ['start_time', 'end_time']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"time_range config missing required field '{field}'")
            # Validate HH:MM format
            if not isinstance(config[field], str) or not re.match(r'^\d{2}:\d{2}$', config[field]):
                raise ValueError(f"{field} must be in HH:MM format (e.g., '23:00'), got '{config[field]}'")
            # Validate time values are valid
            try:
                hours, minutes = map(int, config[field].split(':'))
                if hours < 0 or hours > 23:
                    raise ValueError(f"{field} hours must be between 00-23, got {hours}")
                if minutes < 0 or minutes > 59:
                    raise ValueError(f"{field} minutes must be between 00-59, got {minutes}")
            except ValueError as e:
                raise ValueError(f"Invalid time format for {field}: {str(e)}")

    elif condition_type == 'additional_stops':
        if 'trigger_count' not in config:
            raise ValueError("additional_stops config missing required field 'trigger_count'")

        trigger_count = config['trigger_count']
        if not isinstance(trigger_count, int):
            raise ValueError(f"trigger_count must be an integer, got {type(trigger_count).__name__}")
        if trigger_count < 0:
            raise ValueError(f"trigger_count must be non-negative, got {trigger_count}")
    else:
        # Unknown condition type - log warning but don't fail
        logging.warning(f"Unknown condition_type '{condition_type}' - skipping detailed validation")

@service_bp.route('/services', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant', 'customer')
def list_services():
    try:
        services = ServiceService.get_all()
        return jsonify(schema_many.dump(services)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_services: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def get_service(service_id):
    try:
        service = ServiceService.get_by_id(service_id)
        if not service:
            return jsonify({'error': 'Service not found'}), 404
        return jsonify(schema.dump(service)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_service: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant')
def create_service():
    try:
        data = request.get_json()
        logging.info(f"Raw data received: {data}")

        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active'),
            'is_ancillary': data.get('is_ancillary', False),
            'condition_type': data.get('condition_type'),
            'condition_config': data.get('condition_config'),
            'is_per_occurrence': data.get('is_per_occurrence', False)
        }

        logging.info(f"Processed data: {service_data}")

        # Validate condition_config if ancillary service
        if service_data.get('is_ancillary'):
            try:
                validate_condition_config(
                    service_data.get('condition_type'),
                    service_data.get('condition_config')
                )
            except ValueError as e:
                logging.error(f"condition_config validation error: {str(e)}")
                return jsonify({'error': f"Invalid ancillary configuration: {str(e)}"}), 400

        errors = schema.validate(service_data)
        if errors:
            logging.error(f"Schema validation errors: {errors}")
            return jsonify(errors), 400

        # Create service and get actual sync results
        service, sync_success_count, sync_error_count = ServiceService.create(service_data)
        result = schema.dump(service)

        # Construct accurate message based on sync outcomes
        if sync_success_count > 0:
            if sync_error_count == 0:
                result['message'] = f"Service created successfully and synced to {sync_success_count} contractor pricing lists with default price $0.00"
            else:
                result['message'] = f"Service created successfully. Synced to {sync_success_count} contractors, but {sync_error_count} sync(s) failed."
        elif sync_error_count > 0:
            result['message'] = "Service created but contractor pricing sync failed. Please sync manually."
        else:
            result['message'] = "Service created successfully. No active contractors found for pricing sync."

        logging.info(f"Service created successfully with ID: {service.id}")
        return jsonify(result), 201

    except ServiceError as se:
        return handle_service_error(se)
    except Exception as e:
        logging.error(f"Unhandled error in create_service: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services-with-pricing', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant')
def create_service_with_pricing():
    try:
        data = request.get_json()
        logging.info(f"Creating service with pricing data: {data}")

        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active'),
            'is_ancillary': data.get('is_ancillary', False),
            'condition_type': data.get('condition_type'),
            'condition_config': data.get('condition_config'),
            'is_per_occurrence': data.get('is_per_occurrence', False)
        }

        logging.info(f"Processed service data: {service_data}")

        # Validate condition_config if ancillary service
        if service_data.get('is_ancillary'):
            try:
                validate_condition_config(
                    service_data.get('condition_type'),
                    service_data.get('condition_config')
                )
            except ValueError as e:
                logging.error(f"condition_config validation error: {str(e)}")
                return jsonify({'error': f"Invalid ancillary configuration: {str(e)}"}), 400

        errors = schema.validate(service_data)
        if errors:
            logging.error(f"Service schema validation errors: {errors}")
            return jsonify(errors), 400

        # Create the service first
        service, sync_success_count, sync_error_count = ServiceService.create(service_data)
        logging.info(f"Service created successfully with ID: {service.id}")

        # Extract and create pricing data
        pricing_data = data.get('pricing', [])
        created_pricing = []
        
        if pricing_data:
            from backend.services.services_vehicle_type_price_service import ServicesVehicleTypePriceService
            from backend.schemas.services_vehicle_type_price_schema import ServicesVehicleTypePriceSchema
            
            pricing_schema = ServicesVehicleTypePriceSchema(session=db.session)
            
            for pricing_item in pricing_data:
                pricing_item_data = {
                    'service_id': service.id,
                    'vehicle_type_id': pricing_item.get('vehicle_type_id'),
                    'price': pricing_item.get('price', 0.0)
                }
                
                # Validate pricing data
                pricing_errors = pricing_schema.validate(pricing_item_data)
                if pricing_errors:
                    logging.error(f"Pricing schema validation errors: {pricing_errors}")
                    # Rollback service creation
                    db.session.delete(service)
                    db.session.commit()
                    return jsonify({'error': 'Validation failed for pricing data', 'details': pricing_errors}), 400
                
                try:
                    pricing = ServicesVehicleTypePriceService.create(pricing_item_data)
                    created_pricing.append(pricing)
                except Exception as e:
                    # Rollback service creation
                    db.session.delete(service)
                    db.session.commit()
                    logging.error(f"Error creating pricing: {e}", exc_info=True)
                    return jsonify({'error': f'Could not create pricing: {str(e)}'}), 400
        
        # Return the created service with its pricing
        result = schema.dump(service)
        pricing_list = []
        for p in created_pricing:
            pricing_list.append({
                'id': p.id,
                'service_id': p.service_id,
                'vehicle_type_id': p.vehicle_type_id,
                'price': p.price
            })
        result_dict = {}
        if isinstance(result, dict):
            result_dict = result.copy()
        result_dict['pricing'] = pricing_list
        
        logging.info(f"Service with pricing created successfully: ID {service.id}")
        return jsonify(result_dict), 201
    except ServiceError as se:
        return handle_service_error(se)
    except Exception as e:
        logging.error(f"Unhandled error in create_service_with_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

# Add the new endpoint for creating service with all vehicle type prices
@service_bp.route('/services/create-with-all-pricing', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant')
def create_service_with_all_pricing():
    try:
        data = request.get_json()
        logging.info(f"Creating service with all vehicle type pricing data: {data}")

        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active'),
            'is_ancillary': data.get('is_ancillary', False),
            'condition_type': data.get('condition_type'),
            'condition_config': data.get('condition_config'),
            'is_per_occurrence': data.get('is_per_occurrence', False)
        }

        logging.info(f"Processed service data: {service_data}")
        errors = schema.validate(service_data)
        if errors:
            logging.error(f"Service schema validation errors: {errors}")
            return jsonify(errors), 400

        # Create the service first
        service, sync_success_count, sync_error_count = ServiceService.create(service_data)
        logging.info(f"Service created successfully with ID: {service.id}")
        
        # Get all vehicle types
        from backend.services.vehicle_type_service import VehicleTypeService
        vehicle_types = VehicleTypeService.get_all()
        
        # Create pricing for each vehicle type with the prices provided
        pricing_data = data.get('pricing', {})
        created_pricing = []
        
        from backend.services.services_vehicle_type_price_service import ServicesVehicleTypePriceService
        from backend.schemas.services_vehicle_type_price_schema import ServicesVehicleTypePriceSchema
        
        pricing_schema = ServicesVehicleTypePriceSchema(session=db.session)
        
        for vehicle_type in vehicle_types:
            # Get price for this vehicle type, default to 0.0 if not provided
            price = pricing_data.get(str(vehicle_type.id), 0.0)
            
            # Validate that price is non-negative
            try:
                price_float = float(price)
                if price_float < 0:
                    # Rollback service creation to maintain atomicity
                    db.session.delete(service)
                    db.session.commit()
                    return jsonify({'error': f'Price for vehicle type {vehicle_type.name} cannot be negative.'}), 400
                price = price_float
            except (ValueError, TypeError):
                # Rollback service creation to maintain atomicity
                db.session.delete(service)
                db.session.commit()
                return jsonify({'error': f'Price for vehicle type {vehicle_type.name} must be a valid number.'}), 400
            
            pricing_item_data = {
                'service_id': service.id,
                'vehicle_type_id': vehicle_type.id,
                'price': price
            }
            
            # Validate pricing data
            pricing_errors = pricing_schema.validate(pricing_item_data)
            if pricing_errors:
                logging.error(f"Pricing schema validation errors: {pricing_errors}")
                # Rollback service creation
                db.session.delete(service)
                db.session.commit()
                return jsonify({'error': 'Validation failed for pricing data', 'details': pricing_errors}), 400
            
            try:
                pricing = ServicesVehicleTypePriceService.create(pricing_item_data)
                created_pricing.append(pricing)
            except Exception as e:
                # Rollback service creation
                db.session.delete(service)
                db.session.commit()
                logging.error(f"Error creating pricing: {e}", exc_info=True)
                return jsonify({'error': f'Could not create pricing: {str(e)}'}), 400
        
        # Return the created service with its pricing
        result = schema.dump(service)
        pricing_list = []
        for p in created_pricing:
            vehicle_type = VehicleTypeService.get_by_id(p.vehicle_type_id)
            pricing_list.append({
                'id': p.id,
                'service_id': p.service_id,
                'vehicle_type_id': p.vehicle_type_id,
                'price': p.price,
                'vehicle_type_name': vehicle_type.name if vehicle_type else 'Unknown'
            })
        result_dict = {}
        if isinstance(result, dict):
            result_dict = result.copy()
        result_dict['pricing'] = pricing_list
        
        logging.info(f"Service with all vehicle type pricing created successfully: ID {service.id}")
        return jsonify(result_dict), 201
    except ServiceError as se:
        return handle_service_error(se)
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"Integrity error in create_service_with_all_pricing: {e}", exc_info=True)
        # Check if it's a duplicate name error
        if "UNIQUE constraint failed" in str(e) and "service.name" in str(e):
            return jsonify({'error': 'A service with this name already exists. Please choose a different name.'}), 409
        else:
            return jsonify({'error': 'Could not create service due to a data conflict. Please check your inputs.'}), 409
    except Exception as e:
        logging.error(f"Unhandled error in create_service_with_all_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>', methods=['PUT'])
@roles_accepted('admin', 'manager', 'accountant')
def update_service(service_id):
    try:
        data = request.get_json()
        logging.info(f"Raw update data received for service {service_id}: {data}")
        
        # Handle base_price as float
        if 'base_price' in data:
            if data['base_price'] is None or data['base_price'] == '':
                data['base_price'] = 0.0
            else:
                try:
                    data['base_price'] = float(data['base_price'])
                    if data['base_price'] < 0:
                        return jsonify({'error': 'base_price must be non-negative'}), 400
                except (ValueError, TypeError):
                    return jsonify({'error': 'base_price must be a valid number'}), 400
        
        # Handle numeric fields as Decimal
        decimal_fields = ['additional_ps', 'distance_levy', 'midnight_surcharge']
        for field in decimal_fields:
            if field in data:
                if data[field] is None or data[field] == '':
                    data[field] = Decimal('0.00')
                else:
                    try:
                        data[field] = Decimal(str(data[field]))
                        if data[field] < 0:
                            return jsonify({'error': f'{field} must be non-negative'}), 400
                    except (ValueError, TypeError, InvalidOperation):
                        return jsonify({'error': f'{field} must be a valid number'}), 400
        
        logging.info(f"Processed update data: {data}")

        # Validate condition_config if ancillary service (or being updated to ancillary)
        if data.get('is_ancillary') or 'condition_config' in data or 'condition_type' in data:
            # Get current service to check if it's ancillary
            from backend.models.service import Service
            current_service = Service.query.get(service_id)
            is_ancillary = data.get('is_ancillary', current_service.is_ancillary if current_service else False)

            if is_ancillary:
                condition_type = data.get('condition_type', current_service.condition_type if current_service else None)
                condition_config = data.get('condition_config', current_service.condition_config if current_service else None)

                try:
                    validate_condition_config(condition_type, condition_config)
                except ValueError as e:
                    logging.error(f"condition_config validation error: {str(e)}")
                    return jsonify({'error': f"Invalid ancillary configuration: {str(e)}"}), 400

        errors = schema.validate(data, partial=True)
        if errors:
            logging.error(f"Schema validation errors: {errors}")
            return jsonify(errors), 400
        service = ServiceService.update(service_id, data)
        if not service:
            return jsonify({'error': 'Service not found'}), 404
        result = schema.dump(service)
        logging.info(f"Service updated successfully: ID {service.id}")
        return jsonify(result), 200
    except ServiceError as se:
        return handle_service_error(se)
    except Exception as e:
        logging.error(f"Unhandled error in update_service: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>/update-with-all-pricing', methods=['PUT'])
@roles_accepted('admin', 'manager', 'accountant')
def update_service_with_all_pricing(service_id):
    try:
        data = request.get_json()
        logging.info(f"Updating service with all vehicle type pricing data for service {service_id}: {data}")
        
        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active'),
            'is_ancillary': data.get('is_ancillary', False),
            'condition_type': data.get('condition_type'),
            'condition_config': data.get('condition_config'),
            'is_per_occurrence': data.get('is_per_occurrence', False)
        }
        
        logging.info(f"Processed service data: {service_data}")
        errors = schema.validate(service_data, partial=True)
        if errors:
            logging.error(f"Service schema validation errors: {errors}")
            return jsonify(errors), 400
            
        # Update the service
        service = ServiceService.update(service_id, service_data)
        if not service:
            return jsonify({'error': 'Service not found'}), 404
        logging.info(f"Service updated successfully with ID: {service.id}")
        
        # Handle pricing updates if provided
        if 'pricing' in data:
            pricing_data = data.get('pricing', {})
            
            from backend.services.services_vehicle_type_price_service import ServicesVehicleTypePriceService
            from backend.schemas.services_vehicle_type_price_schema import ServicesVehicleTypePriceSchema
            from backend.services.vehicle_type_service import VehicleTypeService
            
            pricing_schema = ServicesVehicleTypePriceSchema(session=db.session)
            
            # Get existing pricing for this service
            existing_pricing = ServicesVehicleTypePriceService.get_by_service_id(service_id)
            existing_pricing_dict = {p.vehicle_type_id: p for p in existing_pricing}
            
            # Update or create pricing for each entry in the provided data
            updated_pricing = []
            
            for vehicle_type_id_str, price in pricing_data.items():
                try:
                    vehicle_type_id = int(vehicle_type_id_str)
                except ValueError:
                    logging.warning(f"Invalid vehicle_type_id: {vehicle_type_id_str}")
                    continue
                    
                # Validate that price is non-negative
                try:
                    price_float = float(price)
                    if price_float < 0:
                        return jsonify({'error': f'Price for vehicle type {vehicle_type_id} cannot be negative.'}), 400
                    price = price_float
                except (ValueError, TypeError):
                    return jsonify({'error': f'Price for vehicle type {vehicle_type_id} must be a valid number.'}), 400
                    
                price_data = {
                    'service_id': service_id,
                    'vehicle_type_id': vehicle_type_id,
                    'price': price
                }
                
                # Validate pricing data
                pricing_errors = pricing_schema.validate(price_data)
                if pricing_errors:
                    logging.error(f"Pricing schema validation errors: {pricing_errors}")
                    continue
                
                try:
                    # Check if pricing already exists for this service and vehicle type
                    if vehicle_type_id in existing_pricing_dict:
                        # Update existing pricing
                        pricing = ServicesVehicleTypePriceService.update(
                            existing_pricing_dict[vehicle_type_id].id, 
                            price_data
                        )
                    else:
                        # Create new pricing
                        pricing = ServicesVehicleTypePriceService.create(price_data)
                    
                    if pricing:
                        updated_pricing.append(pricing)
                except Exception as e:
                    logging.error(f"Error updating/creating pricing for vehicle type {vehicle_type_id}: {e}", exc_info=True)
                    continue
            
            # Return the updated service with its pricing
            result = schema.dump(service)
            pricing_list = []
            for p in updated_pricing:
                vehicle_type = VehicleTypeService.get_by_id(p.vehicle_type_id)
                pricing_list.append({
                    'id': p.id,
                    'service_id': p.service_id,
                    'vehicle_type_id': p.vehicle_type_id,
                    'price': p.price,
                    'vehicle_type_name': vehicle_type.name if vehicle_type else 'Unknown'
                })
            
            result_dict = {}
            if isinstance(result, dict):
                result_dict = result.copy()
            result_dict['pricing'] = pricing_list
            
            logging.info(f"Service with all vehicle type pricing updated successfully: ID {service.id}")
            return jsonify(result_dict), 200
        else:
            # Return the updated service without pricing changes
            result = schema.dump(service)
            logging.info(f"Service updated successfully without pricing changes: ID {service.id}")
            return jsonify(result), 200
            
    except ServiceError as se:
        return handle_service_error(se)
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"Integrity error in update_service_with_all_pricing: {e}", exc_info=True)
        return jsonify({'error': 'Could not update service due to a data conflict. Please check your inputs.'}), 409
    except Exception as e:
        logging.error(f"Unhandled error in update_service_with_all_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager', 'accountant')
def delete_service(service_id):
    try:
        # Debug: Log the deletion attempt
        logging.info(f"Frontend attempting to delete service {service_id}")
        
        success = ServiceService.delete(service_id)
        if not success:
            return jsonify({'error': 'Service not found'}), 404
        
        logging.info(f"Service {service_id} deleted successfully with cascade")
        return jsonify({'message': 'Service deleted successfully'}), 200
    except ServiceError as se:
        logging.error(f"Service error deleting service {service_id}: {se.message}")
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_service: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>/soft-delete', methods=['PUT'])
@roles_accepted('admin', 'manager', 'accountant')
def toggle_service_soft_delete(service_id):
    try:
        data = request.get_json()
        is_deleted = data.get('is_deleted', True)
        
        service = ServiceService.toggle_soft_delete(service_id, is_deleted)
        if not service:
            return jsonify({'error': 'Service not found'}), 404
            
        return jsonify({
            'message': f'Service {"deleted" if is_deleted else "restored"} successfully',
            'service': schema.dump(service)
        }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in toggle_service_soft_delete: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500