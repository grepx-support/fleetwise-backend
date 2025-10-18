from flask import Blueprint, request, jsonify
from backend.services.vehicle_service import VehicleService, ServiceError
from backend.schemas.vehicle_schema import VehicleSchema
import logging
from flask_security.decorators import roles_required, roles_accepted, auth_required
from flask_security import current_user
from backend.extensions import db

vehicle_bp = Blueprint('vehicle', __name__)
schema = VehicleSchema(session=db.session)
schema_many = VehicleSchema(many=True, session=db.session)

@vehicle_bp.route('/vehicles', methods=['GET'])
@roles_accepted('admin', 'manager')
def list_vehicles():
    try:
        vehicles = VehicleService.get_all()
        return jsonify(schema_many.dump(vehicles)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_vehicles: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_bp.route('/vehicles/<int:vehicle_id>', methods=['GET'])
@auth_required()
def get_vehicle(vehicle_id):
    try:
        vehicle = VehicleService.get_by_id(vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        # Only allow access if admin/manager or the driver assigned to this vehicle
        if current_user.has_role('admin') or current_user.has_role('manager') or getattr(current_user, 'vehicle_id', None) == vehicle_id:
            return jsonify(schema.dump(vehicle)), 200
        return jsonify({'error': 'Forbidden'}), 403
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_vehicle: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_bp.route('/vehicles', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_vehicle():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        vehicle = VehicleService.create(data)
        return jsonify(schema.dump(vehicle)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_vehicle: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_bp.route('/vehicles/<int:vehicle_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_vehicle(vehicle_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        vehicle = VehicleService.update(vehicle_id, data)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        return jsonify(schema.dump(vehicle)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_vehicle: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_bp.route('/vehicles/<int:vehicle_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_vehicle(vehicle_id):
    try:
        success = VehicleService.delete(vehicle_id)
        if not success:
            return jsonify({'error': 'Vehicle not found'}), 404
        return jsonify({'message': 'Vehicle deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_vehicle: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_bp.route('/vehicles/<int:vehicle_id>/soft-delete', methods=['PUT'])
@roles_accepted('admin', 'manager')
def toggle_vehicle_soft_delete(vehicle_id):
    try:
        data = request.get_json()
        is_deleted = data.get('is_deleted', True)
        
        vehicle = VehicleService.toggle_soft_delete(vehicle_id, is_deleted)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
            
        return jsonify({
            'message': f'Vehicle {"deleted" if is_deleted else "restored"} successfully',
            'vehicle': schema.dump(vehicle)
        }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in toggle_vehicle_soft_delete: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
