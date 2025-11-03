from flask import Blueprint, request, jsonify
from backend.services.role_service import RoleService, ServiceError
from backend.schemas.role_schema import RoleSchema
import logging
from flask_security import roles_required, roles_accepted
from backend.extensions import db

role_bp = Blueprint('role', __name__)
schema = RoleSchema()
schema_many = RoleSchema(many=True)

@role_bp.route('/roles', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def list_roles():
    try:
        roles = RoleService.get_all()
        return jsonify(schema_many.dump(roles)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_roles: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@role_bp.route('/roles/<int:role_id>', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def get_role(role_id):
    try:
        role = RoleService.get_by_id(role_id)
        if not role:
            return jsonify({'error': 'Role not found'}), 404
        return jsonify(schema.dump(role)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_role: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@role_bp.route('/roles', methods=['POST'])
@roles_required('admin')
def create_role():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        role = RoleService.create(data)
        return jsonify(schema.dump(role)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_role: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@role_bp.route('/roles/<int:role_id>', methods=['PUT'])
@roles_required('admin')
def update_role(role_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        role = RoleService.update(role_id, data)
        if not role:
            return jsonify({'error': 'Role not found'}), 404
        return jsonify(schema.dump(role)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_role: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@role_bp.route('/roles/<int:role_id>', methods=['DELETE'])
@roles_required('admin')
def delete_role(role_id):
    try:
        success = RoleService.delete(role_id)
        if not success:
            return jsonify({'error': 'Role not found'}), 404
        return jsonify({'message': 'Role deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_role: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500 