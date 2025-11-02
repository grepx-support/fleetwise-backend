from flask import Blueprint, request, jsonify
from backend.services.customer_service import CustomerService, ServiceError
from backend.schemas.customer_schema import CustomerSchema
import logging
from flask_security.decorators import roles_required, roles_accepted, auth_required
from flask_security import current_user
from backend.extensions import db

customer_bp = Blueprint('customer', __name__)
schema = CustomerSchema(session=db.session)
schema_many = CustomerSchema(many=True, session=db.session)

@customer_bp.route('/customers', methods=['GET'])
@auth_required()
def list_customers():
    try:
        if current_user.has_role('admin') or current_user.has_role('manager') or current_user.has_role('accountant'):
            customers = CustomerService.get_all()
        elif current_user.has_role('customer'):
            # Only return the customer associated with logged in user
            if not current_user.customer_id:
                return jsonify({'error': 'Customer profile missing'}), 403
            
            single_customer = CustomerService.get_by_id(current_user.customer_id)
            
            if not single_customer:
                return jsonify({'error': 'Customer not found'}), 404
            
            customers = [single_customer]  # Return as a list for frontend compatibility
        else:
            return jsonify({'error': 'Forbidden'}), 403

        return jsonify(schema_many.dump(customers)), 200
        
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_customers: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@customer_bp.route('/customers/<int:customer_id>', methods=['GET'])
@auth_required()
def get_customer(customer_id):
    try:
        customer = CustomerService.get_by_id(customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        # Only allow access if admin/manager or the customer themselves
        if current_user.has_role('admin') or current_user.has_role('manager') or current_user.id == customer_id:
            return jsonify(schema.dump(customer)), 200
        return jsonify({'error': 'Forbidden'}), 403
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@customer_bp.route('/customers', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant')
def create_customer():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        customer = CustomerService.create(data)
        return jsonify(schema.dump(customer)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@customer_bp.route('/customers/<int:customer_id>', methods=['PUT'])
@roles_accepted('admin', 'manager', 'accountant')
def update_customer(customer_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        customer = CustomerService.update(customer_id, data)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        return jsonify(schema.dump(customer)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@customer_bp.route('/customers/<int:customer_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager', 'accountant')
def delete_customer(customer_id):
    try:
        # Debug: Log the deletion attempt
        logging.info(f"Frontend attempting to delete customer {customer_id}")
        
        # For frontend calls, automatically cascade delete for simplicity
        # Frontend users expect delete to work without complex parameters
        force_cascade = True
        
        success = CustomerService.delete(customer_id, force_cascade=force_cascade)
        if not success:
            return jsonify({'error': 'Customer not found'}), 404
        
        logging.info(f"Customer {customer_id} deleted successfully with cascade")
        return jsonify({'message': 'Customer deleted successfully'}), 200
    except ServiceError as se:
        logging.error(f"Service error deleting customer {customer_id}: {se.message}")
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_customer: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@customer_bp.route('/customers/<int:customer_id>/soft-delete', methods=['PUT'])
@roles_accepted('admin', 'manager', 'accountant')
def toggle_customer_soft_delete(customer_id):
    try:
        data = request.get_json()
        is_deleted = data.get('is_deleted', True)
        
        customer = CustomerService.toggle_soft_delete(customer_id, is_deleted)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
            
        return jsonify({
            'message': f'Customer {"deleted" if is_deleted else "restored"} successfully',
            'customer': schema.dump(customer)
        }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in toggle_customer_soft_delete: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
