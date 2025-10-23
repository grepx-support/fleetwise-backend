from flask import Blueprint, request, jsonify
from backend.services.contractor_service import ContractorService, ServiceError
from backend.schemas.contractor_schema import ContractorSchema
import logging
from flask_security.decorators import roles_required, roles_accepted, auth_required
from backend.extensions import db

contractor_bp = Blueprint('contractor', __name__)
schema = ContractorSchema(session=db.session)
schema_many = ContractorSchema(many=True, session=db.session)

@contractor_bp.route('/contractors', methods=['GET'])
@roles_accepted('admin', 'manager')
def list_contractors():
    try:
        contractors = ContractorService.get_all()
        return jsonify(schema_many.dump(contractors)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_contractors: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>', methods=['GET'])
@auth_required()
def get_contractor(contractor_id):
    try:
        contractor = ContractorService.get_by_id(contractor_id)
        if not contractor:
            return jsonify({'error': 'Contractor not found'}), 404
        return jsonify(schema.dump(contractor)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_contractor: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_contractor():
    try:
        data = request.get_json()
        
        # Extract contractor details
        contractor_data = {
            'name': data.get('name'),
            'contact_person': data.get('contact_person'),
            'contact_number': data.get('contact_number'),
            'email': data.get('email'),
            'status': data.get('status', 'Active')
        }
        
        # Validate contractor data
        errors = schema.validate(contractor_data)
        if errors:
            return jsonify(errors), 400
            
        # Create the contractor
        contractor = ContractorService.create(contractor_data)
        
        # If pricing data is provided, create pricing entries
        pricing_data = data.get('pricing_data', [])
        if pricing_data and isinstance(pricing_data, list):
            # Validate each pricing item
            for pricing_item in pricing_data:
                if 'service_id' not in pricing_item or 'cost' not in pricing_item:
                    return jsonify({'error': 'Each pricing item must have service_id and cost'}), 400
                
                cost = pricing_item['cost']
                
                # Validate that cost is non-negative
                if cost < 0:
                    return jsonify({'error': f'Cost for service {pricing_item["service_id"]} must be non-negative'}), 400
            
            # Create pricing entries
            ContractorService.bulk_update_contractor_pricing(contractor.id, pricing_data)
        
        # Return the created contractor with its pricing
        result = schema.dump(contractor)
        
        # Add pricing information to the response
        pricing = ContractorService.get_contractor_pricing(contractor.id)
        result['pricing'] = []
        for p in pricing:
            result['pricing'].append({
                'id': p.id,
                'contractor_id': p.contractor_id,
                'service_id': p.service_id,
                'service_name': p.service.name if p.service else None,
                'cost': p.cost
            })
        
        return jsonify(result), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_contractor: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@contractor_bp.route('/contractors/<int:contractor_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_contractor(contractor_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        contractor = ContractorService.update(contractor_id, data)
        if not contractor:
            return jsonify({'error': 'Contractor not found'}), 404
        return jsonify(schema.dump(contractor)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_contractor: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_contractor(contractor_id):
    try:
        success = ContractorService.delete(contractor_id)
        if not success:
            return jsonify({'error': 'Contractor not found'}), 404
        return jsonify({'message': 'Contractor deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_contractor: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>/soft-delete', methods=['PUT'])
@roles_accepted('admin', 'manager')
def toggle_contractor_soft_delete(contractor_id):
    try:
        data = request.get_json()
        is_deleted = data.get('is_deleted', True)
        
        contractor = ContractorService.toggle_soft_delete(contractor_id, is_deleted)
        if not contractor:
            return jsonify({'error': 'Contractor not found'}), 404
            
        return jsonify({
            'message': f'Contractor {"deleted" if is_deleted else "restored"} successfully',
            'contractor': schema.dump(contractor)
        }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in toggle_contractor_soft_delete: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/active', methods=['GET'])
@auth_required()
def list_active_contractors():
    try:
        contractors = ContractorService.get_active_contractors()
        return jsonify(schema_many.dump(contractors)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_active_contractors: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>/pricing', methods=['GET'])
@auth_required()
def get_contractor_pricing(contractor_id):
    try:
        pricing = ContractorService.get_contractor_pricing(contractor_id)
        # Convert to a more usable format
        result = []
        for p in pricing:
            result.append({
                'id': p.id,
                'contractor_id': p.contractor_id,
                'service_id': p.service_id,
                'service_name': p.service.name if p.service else None,
                'cost': p.cost
            })
        return jsonify(result), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_contractor_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>/pricing', methods=['POST'])
@roles_accepted('admin', 'manager')
def update_contractor_pricing(contractor_id):
    try:
        data = request.get_json()
        
        # Check if this is a bulk update (pricing_data exists) or single update
        if not data:
            return jsonify({'error': 'Missing data'}), 400
            
        if 'pricing_data' in data:
            # Handle bulk update
            pricing_data = data['pricing_data']
            if not isinstance(pricing_data, list):
                return jsonify({'error': 'pricing_data must be a list'}), 400
            
            # Validate each pricing item
            for pricing_item in pricing_data:
                if 'service_id' not in pricing_item or 'cost' not in pricing_item:
                    return jsonify({'error': 'Each pricing item must have service_id and cost'}), 400
                
                cost = pricing_item['cost']
                
                # Validate that cost is non-negative
                if cost < 0:
                    return jsonify({'error': f'Cost for service {pricing_item["service_id"]} must be non-negative'}), 400
            
            updated_pricing = ContractorService.bulk_update_contractor_pricing(contractor_id, pricing_data)
            
            # Convert to JSON-serializable format
            result = []
            for pricing in updated_pricing:
                result.append({
                    'id': pricing.id,
                    'contractor_id': pricing.contractor_id,
                    'service_id': pricing.service_id,
                    'cost': pricing.cost
                })
            
            return jsonify(result), 200
        else:
            # Handle single update
            if 'service_id' not in data or 'cost' not in data:
                return jsonify({'error': 'Missing service_id or cost'}), 400
            
            service_id = data['service_id']
            cost = data['cost']
            
            # Validate that cost is non-negative
            if cost < 0:
                return jsonify({'error': 'Cost must be non-negative'}), 400
            
            pricing = ContractorService.update_contractor_pricing(contractor_id, service_id, cost)
            return jsonify({
                'id': pricing.id,
                'contractor_id': pricing.contractor_id,
                'service_id': pricing.service_id,
                'cost': pricing.cost
            }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_contractor_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
    
@contractor_bp.route('/contractors/download/<int:bill_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def download_contractor_invoice(bill_id):
    try:
        response = ContractorService.contractor_invoice_download(bill_id)
        if not response:
            return jsonify({'error': 'Contractor Invoice not found'}), 404
        return response
    except Exception as e:
        logging.error(f"Unhandled error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to generate invoice PDF'}), 500
    