from flask import Blueprint, request, jsonify
from backend.services.driver_commission_service import DriverCommissionService, ServiceError
from backend.schemas.driver_commission_schema import DriverCommissionSchema
import logging
from flask_security import roles_required, roles_accepted
from backend.extensions import db

driver_commission_bp = Blueprint('driver_commission', __name__)
schema = DriverCommissionSchema(session=db.session)
schema_many = DriverCommissionSchema(many=True, session=db.session)

@driver_commission_bp.route('/driver_commissions', methods=['GET'])
@roles_accepted('admin', 'manager')
def list_driver_commissions():
    try:
        commissions = DriverCommissionService.get_all()
        return jsonify(schema_many.dump(commissions)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_driver_commissions: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_commission_bp.route('/driver_commissions/<int:commission_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def get_driver_commission(commission_id):
    try:
        commission = DriverCommissionService.get_by_id(commission_id)
        if not commission:
            return jsonify({'error': 'DriverCommission not found'}), 404
        return jsonify(schema.dump(commission)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_driver_commission: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_commission_bp.route('/driver_commissions', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_driver_commission():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        commission = DriverCommissionService.create(data)
        return jsonify(schema.dump(commission)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_driver_commission: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_commission_bp.route('/driver_commissions/<int:commission_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_driver_commission(commission_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        commission = DriverCommissionService.update(commission_id, data)
        if not commission:
            return jsonify({'error': 'DriverCommission not found'}), 404
        return jsonify(schema.dump(commission)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_driver_commission: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_commission_bp.route('/driver_commissions/<int:commission_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_driver_commission(commission_id):
    try:
        success = DriverCommissionService.delete(commission_id)
        if not success:
            return jsonify({'error': 'DriverCommission not found'}), 404
        return jsonify({'message': 'DriverCommission deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_driver_commission: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500 