from flask import Blueprint, request, jsonify
from backend.services.services_vehicle_type_price_service import ServicesVehicleTypePriceService, ServiceError
from backend.schemas.services_vehicle_type_price_schema import ServicesVehicleTypePriceSchema
import logging
from flask_security.decorators import roles_accepted
from backend.extensions import db

services_vehicle_type_price_bp = Blueprint('services_vehicle_type_price', __name__)
schema = ServicesVehicleTypePriceSchema(session=db.session)
schema_many = ServicesVehicleTypePriceSchema(many=True, session=db.session)

@services_vehicle_type_price_bp.route('/services-vehicle-type-prices', methods=['GET'])
@roles_accepted('admin', 'manager')
def list_services_vehicle_type_prices():
    try:
        # Check if service_id parameter is provided
        service_id = request.args.get('service_id')
        
        if service_id:
            # Filter by service_id if provided
            services_vehicle_type_prices = ServicesVehicleTypePriceService.get_by_service_id(service_id)
        else:
            # Get all if no service_id provided
            services_vehicle_type_prices = ServicesVehicleTypePriceService.get_all()
            
        return jsonify(schema_many.dump(services_vehicle_type_prices)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_services_vehicle_type_prices: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@services_vehicle_type_price_bp.route('/services-vehicle-type-prices/<int:services_vehicle_type_price_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def get_services_vehicle_type_price(services_vehicle_type_price_id):
    try:
        services_vehicle_type_price = ServicesVehicleTypePriceService.get_by_id(services_vehicle_type_price_id)
        if not services_vehicle_type_price:
            return jsonify({'error': 'Service vehicle type price not found'}), 404
        return jsonify(schema.dump(services_vehicle_type_price)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_services_vehicle_type_price: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@services_vehicle_type_price_bp.route('/services-vehicle-type-prices', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_services_vehicle_type_price():
    try:
        data = request.get_json()
        # Log the incoming data for debugging
        logging.info(f"Creating service vehicle type price with data: {data}")
        
        # Validate price is non-negative
        price = data.get('price', 0.0)
        try:
            price_float = float(price)
            if price_float < 0:
                return jsonify({'error': 'Price cannot be negative.'}), 400
            data['price'] = price_float
        except (ValueError, TypeError):
            return jsonify({'error': 'Price must be a valid number.'}), 400
        
        # Validate the data
        try:
            errors = schema.validate(data)
            if errors:
                logging.warning(f"Validation errors: {errors}")
                return jsonify({'error': 'Validation failed', 'details': errors}), 400
        except Exception as e:
            logging.error(f"Schema validation error: {e}", exc_info=True)
            return jsonify({'error': 'Invalid data format'}), 400
            
        services_vehicle_type_price = ServicesVehicleTypePriceService.create(data)
        return jsonify(schema.dump(services_vehicle_type_price)), 201
    except ServiceError as se:
        logging.warning(f"ServiceError in create_services_vehicle_type_price: {se.message}")
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_services_vehicle_type_price: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@services_vehicle_type_price_bp.route('/services-vehicle-type-prices/<int:services_vehicle_type_price_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_services_vehicle_type_price(services_vehicle_type_price_id):
    try:
        data = request.get_json()
        # Log the incoming data for debugging
        logging.info(f"Updating service vehicle type price {services_vehicle_type_price_id} with data: {data}")
        
        # Validate price is non-negative if provided
        if 'price' in data:
            price = data['price']
            try:
                price_float = float(price)
                if price_float < 0:
                    return jsonify({'error': 'Price cannot be negative.'}), 400
                data['price'] = price_float
            except (ValueError, TypeError):
                return jsonify({'error': 'Price must be a valid number.'}), 400
        
        # Validate the data
        try:
            errors = schema.validate(data, partial=True)
            if errors:
                logging.warning(f"Validation errors: {errors}")
                return jsonify({'error': 'Validation failed', 'details': errors}), 400
        except Exception as e:
            logging.error(f"Schema validation error: {e}", exc_info=True)
            return jsonify({'error': 'Invalid data format'}), 400
            
        services_vehicle_type_price = ServicesVehicleTypePriceService.update(services_vehicle_type_price_id, data)
        if not services_vehicle_type_price:
            return jsonify({'error': 'Service vehicle type price not found'}), 404
        return jsonify(schema.dump(services_vehicle_type_price)), 200
    except ServiceError as se:
        logging.warning(f"ServiceError in update_services_vehicle_type_price: {se.message}")
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_services_vehicle_type_price: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@services_vehicle_type_price_bp.route('/services-vehicle-type-prices/<int:services_vehicle_type_price_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_services_vehicle_type_price(services_vehicle_type_price_id):
    try:
        success = ServicesVehicleTypePriceService.delete(services_vehicle_type_price_id)
        if not success:
            return jsonify({'error': 'Service vehicle type price not found'}), 404
        return jsonify({'message': 'Service vehicle type price deleted'}), 200
    except ServiceError as se:
        logging.warning(f"ServiceError in delete_services_vehicle_type_price: {se.message}")
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_services_vehicle_type_price: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500