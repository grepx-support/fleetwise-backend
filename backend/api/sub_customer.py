from flask import Blueprint, request, jsonify
from backend.services.sub_customer_service import SubCustomerService, ServiceError
from backend.schemas.sub_customer_schema import SubCustomerSchema
import logging
from flask_security import roles_required, roles_accepted, auth_required, current_user
from backend.extensions import db

sub_customer_bp = Blueprint('sub_customer', __name__)
schema = SubCustomerSchema(session=db.session)
schema_many = SubCustomerSchema(many=True, session=db.session)

@sub_customer_bp.route('/sub_customers', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def list_sub_customers():
    try:
        sub_customers = SubCustomerService.get_all()
        return jsonify(schema_many.dump(sub_customers)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_sub_customers: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@sub_customer_bp.route('/sub_customers/<int:sub_customer_id>', methods=['GET'])
@auth_required()
def get_sub_customer(sub_customer_id):
    try:
        sub_customer = SubCustomerService.get_by_id(sub_customer_id)
        if not sub_customer:
            return jsonify({'error': 'SubCustomer not found'}), 404
        # Only allow access if admin/manager or the customer who owns the sub-customer
        if current_user.has_role('admin') or current_user.has_role('manager') or sub_customer.customer_id == current_user.id:
            return jsonify(schema.dump(sub_customer)), 200
        return jsonify({'error': 'Forbidden'}), 403
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_sub_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@sub_customer_bp.route('/sub_customers', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant')
def create_sub_customer():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        sub_customer = SubCustomerService.create(data)
        return jsonify(schema.dump(sub_customer)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_sub_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@sub_customer_bp.route('/sub_customers/<int:sub_customer_id>', methods=['PUT'])
@roles_accepted('admin', 'manager', 'accountant')
def update_sub_customer(sub_customer_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        sub_customer = SubCustomerService.update(sub_customer_id, data)
        if not sub_customer:
            return jsonify({'error': 'SubCustomer not found'}), 404
        return jsonify(schema.dump(sub_customer)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_sub_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@sub_customer_bp.route('/sub_customers/<int:sub_customer_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager', 'accountant')
def delete_sub_customer(sub_customer_id):
    try:
        success = SubCustomerService.delete(sub_customer_id)
        if not success:
            return jsonify({'error': 'SubCustomer not found'}), 404
        return jsonify({'message': 'SubCustomer deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_sub_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500 