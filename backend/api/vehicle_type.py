from flask import Blueprint, request, jsonify
from backend.services.vehicle_type_service import VehicleTypeService, ServiceError
from backend.schemas.vehicle_type_schema import VehicleTypeSchema
import logging
from flask_security.decorators import roles_required, roles_accepted, auth_required
from backend.extensions import db

vehicle_type_bp = Blueprint('vehicle_type', __name__)
schema = VehicleTypeSchema(session=db.session)
schema_many = VehicleTypeSchema(many=True, session=db.session)

@vehicle_type_bp.route('/vehicle-types', methods=['GET'])
@roles_accepted('admin', 'manager','accountant','customer')
def list_vehicle_types():
    try:
        vehicle_types = VehicleTypeService.get_all()
        return jsonify(schema_many.dump(vehicle_types)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_vehicle_types: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_type_bp.route('/vehicle-types/<int:vehicle_type_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def get_vehicle_type(vehicle_type_id):
    try:
        vehicle_type = VehicleTypeService.get_by_id(vehicle_type_id)
        if not vehicle_type:
            return jsonify({'error': 'Vehicle type not found'}), 404
        return jsonify(schema.dump(vehicle_type)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_vehicle_type: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_type_bp.route('/vehicle-types', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_vehicle_type():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        vehicle_type = VehicleTypeService.create(data)
        return jsonify(schema.dump(vehicle_type)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_vehicle_type: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_type_bp.route('/vehicle-types/<int:vehicle_type_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_vehicle_type(vehicle_type_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        vehicle_type = VehicleTypeService.update(vehicle_type_id, data)
        if not vehicle_type:
            return jsonify({'error': 'Vehicle type not found'}), 404
        return jsonify(schema.dump(vehicle_type)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_vehicle_type: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_type_bp.route('/vehicle-types/<int:vehicle_type_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_vehicle_type(vehicle_type_id):
    try:
        success = VehicleTypeService.delete(vehicle_type_id)
        if not success:
            return jsonify({'error': 'Vehicle type not found'}), 404
        return jsonify({'message': 'Vehicle type deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_vehicle_type: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@vehicle_type_bp.route('/vehicle-types/<int:vehicle_type_id>/soft-delete', methods=['PUT'])
@roles_accepted('admin', 'manager')
def toggle_vehicle_type_soft_delete(vehicle_type_id):
    try:
        data = request.get_json()
        is_deleted = data.get('is_deleted', True)
        
        vehicle_type = VehicleTypeService.toggle_soft_delete(vehicle_type_id, is_deleted)
        if not vehicle_type:
            return jsonify({'error': 'Vehicle type not found'}), 404
            
        return jsonify({
            'message': f'Vehicle type {"deleted" if is_deleted else "restored"} successfully',
            'vehicle_type': schema.dump(vehicle_type)
        }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in toggle_vehicle_type_soft_delete: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500