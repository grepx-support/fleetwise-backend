from flask import Blueprint, request, jsonify
from backend.services.service_service import ServiceService, ServiceError
from backend.schemas.service_schema import ServiceSchema
import logging
from flask_security.decorators import roles_required, roles_accepted, auth_required
from backend.extensions import db
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import IntegrityError

service_bp = Blueprint('service', __name__)
schema = ServiceSchema(session=db.session)
schema_many = ServiceSchema(many=True, session=db.session)

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
@roles_accepted('admin', 'manager')
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
@roles_accepted('admin', 'manager')
def create_service():
    try:
        data = request.get_json()
        logging.info(f"Raw data received: {data}")
        
        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active')
        }
        
        logging.info(f"Processed data: {service_data}")
        errors = schema.validate(service_data)
        if errors:
            logging.error(f"Schema validation errors: {errors}")
            return jsonify(errors), 400
        service = ServiceService.create(service_data)
        result = schema.dump(service)
        logging.info(f"Service created successfully with ID: {service.id}")
        return jsonify(result), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_service: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services-with-pricing', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_service_with_pricing():
    try:
        data = request.get_json()
        logging.info(f"Creating service with pricing data: {data}")
        
        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active')
        }
        
        logging.info(f"Processed service data: {service_data}")
        errors = schema.validate(service_data)
        if errors:
            logging.error(f"Service schema validation errors: {errors}")
            return jsonify(errors), 400
            
        # Create the service first
        service = ServiceService.create(service_data)
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
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_service_with_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

# Add the new endpoint for creating service with all vehicle type prices
@service_bp.route('/services/create-with-all-pricing', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_service_with_all_pricing():
    try:
        data = request.get_json()
        logging.info(f"Creating service with all vehicle type pricing data: {data}")
        
        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active')
        }
        
        logging.info(f"Processed service data: {service_data}")
        errors = schema.validate(service_data)
        if errors:
            logging.error(f"Service schema validation errors: {errors}")
            return jsonify(errors), 400
            
        # Create the service first
        service = ServiceService.create(service_data)
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
        return jsonify({'error': se.message}), 400
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"Integrity error in create_service_with_all_pricing: {e}", exc_info=True)
        # Check if it's a duplicate name error
        if "UNIQUE constraint failed" in str(e) and "service.name" in str(e):
            return jsonify({'error': 'A service with this name already exists. Please choose a different name.'}), 400
        else:
            return jsonify({'error': 'Could not create service due to a data conflict. Please check your inputs.'}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_service_with_all_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
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
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_service: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>/update-with-all-pricing', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_service_with_all_pricing(service_id):
    try:
        data = request.get_json()
        logging.info(f"Updating service with all vehicle type pricing data for service {service_id}: {data}")
        
        # Extract only the fields that exist in the Service model
        service_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'status': data.get('status', 'Active')
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
        return jsonify({'error': se.message}), 400
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"Integrity error in update_service_with_all_pricing: {e}", exc_info=True)
        return jsonify({'error': 'Could not update service due to a data conflict. Please check your inputs.'}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_service_with_all_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@service_bp.route('/services/<int:service_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
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
@roles_accepted('admin', 'manager')
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