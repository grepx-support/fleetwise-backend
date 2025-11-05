from flask import Blueprint, request, jsonify
from backend.services.contractor_service import ContractorService, ServiceError
from backend.services.contractor_service_pricing_service import ContractorServicePricingService
from backend.models.contractor_service_pricing import ContractorServicePricing
from backend.schemas.contractor_schema import ContractorSchema
import logging
from flask_security.decorators import roles_required, roles_accepted, auth_required
from flask_security import current_user
from backend.extensions import db

contractor_bp = Blueprint('contractor', __name__)
schema = ContractorSchema(session=db.session)
schema_many = ContractorSchema(many=True, session=db.session)

@contractor_bp.route('/contractors', methods=['GET'])
@auth_required()
def list_contractors():
    try:
        # Admin / Manager / Accountant → view ALL
        if current_user.has_role('admin') or current_user.has_role('manager') or current_user.has_role('accountant'):
            contractors = ContractorService.get_all()

        # Customer → view ONLY internal contractor (ID = 1)
        elif current_user.has_role('customer'):
            contractors = ContractorService.get_by_id(1)
            if not contractors:
                return jsonify([]), 200
            contractors = [contractors]  # Convert to list for schema dump

        # All other roles → forbidden
        else:
            return jsonify({'error': 'Forbidden'}), 403

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
@roles_accepted('admin', 'manager', 'accountant')
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
            # Check if this is vehicle-type-specific pricing (has vehicle_type_id)
            if pricing_data and 'vehicle_type_id' in pricing_data[0]:
                # Handle vehicle-type-specific pricing
                for pricing_item in pricing_data:
                    if 'service_id' not in pricing_item or 'vehicle_type_id' not in pricing_item or 'cost' not in pricing_item:
                        return jsonify({'error': 'Each pricing item must have service_id, vehicle_type_id, and cost'}), 400
                    
                    service_id = pricing_item['service_id']
                    vehicle_type_id = pricing_item['vehicle_type_id']
                    cost = pricing_item['cost']
                    
                    # Validate that cost is non-negative
                    if cost < 0:
                        return jsonify({'error': f'Cost for service {service_id} and vehicle type {vehicle_type_id} must be non-negative'}), 400
                    
                    # Validate service exists and is active
                    from backend.models.service import Service
                    service = Service.query.filter_by(id=service_id, is_deleted=False).first()
                    if not service:
                        return jsonify({'error': f'Service {service_id} not found or inactive'}), 400
                    
                    # Create or update the pricing entry
                    ContractorServicePricingService.update_pricing(
                        contractor.id, service_id, vehicle_type_id, cost
                    )
            else:
                # Handle regular service-based pricing
                # Require explicit vehicle_type_id in each pricing item
                for pricing_item in pricing_data:
                    if 'vehicle_type_id' not in pricing_item:
                        return jsonify({
                            'error': 'vehicle_type_id is required for each pricing item'
                        }), 400
                
                # Validate each pricing item
                for pricing_item in pricing_data:
                    if 'service_id' not in pricing_item or 'cost' not in pricing_item:
                        return jsonify({'error': 'Each pricing item must have service_id and cost'}), 400
                    
                    service_id = pricing_item['service_id']
                    cost = pricing_item['cost']
                    
                    # Validate that cost is non-negative
                    if cost < 0:
                        return jsonify({'error': f'Cost for service {service_id} must be non-negative'}), 400
                    
                    # Validate service exists and is active
                    from backend.models.service import Service
                    service = Service.query.filter_by(id=service_id, is_deleted=False).first()
                    if not service:
                        return jsonify({'error': f'Service {service_id} not found or inactive'}), 400
                
                # Create pricing entries
                ContractorService.bulk_update_contractor_pricing(contractor.id, pricing_data)
        
        # Return the created contractor with its pricing
        contractor_data = schema.dump(contractor)
        
        # Create a new dictionary to avoid type issues
        result = {}
        # Copy all contractor data
        for key in contractor_data:
            result[key] = contractor_data[key]
        
        # Add pricing information to the response
        pricing = ContractorService.get_contractor_pricing(contractor.id)
        result['pricing'] = []
        for p in pricing:
            result['pricing'].append({
                'id': p.id,
                'contractor_id': p.contractor_id,
                'service_id': p.service_id,
                'vehicle_type_id': p.vehicle_type_id,
                'service_name': p.service.name if p.service else None,
                'vehicle_type_name': p.vehicle_type.name if p.vehicle_type else None,
                'cost': p.cost
            })
        
        return jsonify(result), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_contractor: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@contractor_bp.route('/contractors/<int:contractor_id>', methods=['PUT'])
@roles_accepted('admin', 'manager', 'accountant')
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
@roles_accepted('admin', 'manager', 'accountant')
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
@roles_accepted('admin', 'manager', 'accountant')
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
                'vehicle_type_id': p.vehicle_type_id,
                'service_name': p.service.name if p.service else None,
                'vehicle_type_name': p.vehicle_type.name if p.vehicle_type else None,
                'cost': p.cost
            })
        return jsonify(result), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_contractor_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>/pricing', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant')
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
                
                service_id = pricing_item['service_id']
                cost = pricing_item['cost']
                
                # Validate that cost is non-negative
                if cost < 0:
                    return jsonify({'error': f'Cost for service {service_id} must be non-negative'}), 400
                
                # Validate service exists and is active
                from backend.models.service import Service
                service = Service.query.filter_by(id=service_id, is_deleted=False).first()
                if not service:
                    return jsonify({'error': f'Service {service_id} not found or inactive'}), 400
            
            updated_pricing = ContractorService.bulk_update_contractor_pricing(contractor_id, pricing_data)
            
            # Convert to JSON-serializable format
            result = []
            for pricing in updated_pricing:
                result.append({
                    'id': pricing.id,
                    'contractor_id': pricing.contractor_id,
                    'service_id': pricing.service_id,
                    'vehicle_type_id': pricing.vehicle_type_id,
                    'cost': pricing.cost
                })
            
            return jsonify(result), 200
        else:
            # Handle single update
            if 'service_id' not in data or 'cost' not in data:
                return jsonify({'error': 'Missing service_id or cost'}), 400
            
            service_id = data['service_id']
            cost = data['cost']
            # Get vehicle_type_id from data, default to 1 (E-Class Sedan) if not provided
            vehicle_type_id = data.get('vehicle_type_id', 1)
            
            # Validate that cost is non-negative
            if cost < 0:
                return jsonify({'error': 'Cost must be non-negative'}), 400
            
            # Validate service exists and is active
            from backend.models.service import Service
            service = Service.query.filter_by(id=service_id, is_deleted=False).first()
            if not service:
                return jsonify({'error': f'Service {service_id} not found or inactive'}), 400
            
            pricing = ContractorService.update_contractor_pricing(contractor_id, service_id, vehicle_type_id, cost)
            return jsonify({
                'id': pricing.id,
                'contractor_id': pricing.contractor_id,
                'service_id': pricing.service_id,
                'vehicle_type_id': pricing.vehicle_type_id,
                'cost': pricing.cost
            }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_contractor_pricing: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
    
@contractor_bp.route('/contractors/download/<int:bill_id>', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def download_contractor_invoice(bill_id):
    try:
        response = ContractorService.contractor_invoice_download(bill_id)
        if not response:
            return jsonify({'error': 'Contractor Invoice not found'}), 404
        return response
    except Exception as e:
        logging.error(f"Unhandled error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to generate invoice PDF'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>/pricing/vehicle-type', methods=['GET'])
@auth_required()
def get_contractor_pricing_by_vehicle_type(contractor_id):
    try:
        # Get optional query parameters
        service_id = request.args.get('service_id', type=int)
        vehicle_type_id = request.args.get('vehicle_type_id', type=int)
        
        # Get pricing based on provided parameters
        if service_id and vehicle_type_id:
            # Get specific pricing for contractor, service, and vehicle type
            pricing = ContractorServicePricingService.get_pricing(contractor_id, service_id, vehicle_type_id)
            if not pricing:
                return jsonify({'error': 'Pricing not found'}), 404
                
            result = {
                'id': pricing.id,
                'contractor_id': pricing.contractor_id,
                'service_id': pricing.service_id,
                'vehicle_type_id': pricing.vehicle_type_id,
                'service_name': pricing.service.name if pricing.service else None,
                'vehicle_type_name': pricing.vehicle_type.name if pricing.vehicle_type else None,
                'cost': pricing.cost
            }
            return jsonify(result), 200
        else:
            # Get all pricing for the contractor
            all_pricing = ContractorServicePricing.query.filter_by(contractor_id=contractor_id).all()
            logging.debug(f"Found {len(all_pricing)} pricing records for contractor {contractor_id}")
            result = []
            for pricing in all_pricing:
                result.append({
                    'id': pricing.id,
                    'contractor_id': pricing.contractor_id,
                    'service_id': pricing.service_id,
                    'vehicle_type_id': pricing.vehicle_type_id,
                    'service_name': pricing.service.name if pricing.service else None,
                    'vehicle_type_name': pricing.vehicle_type.name if pricing.vehicle_type else None,
                    'cost': pricing.cost
                })
            logging.debug(f"Returning {len(result)} pricing records for contractor {contractor_id}")
            return jsonify(result), 200
    except Exception as e:
        logging.error(f"Unhandled error in get_contractor_pricing_by_vehicle_type: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@contractor_bp.route('/contractors/<int:contractor_id>/pricing/vehicle-type', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant')
def update_contractor_pricing_by_vehicle_type(contractor_id):
    try:
        # Validate contractor exists and is active
        from backend.models.contractor import Contractor
        contractor = Contractor.query.filter_by(id=contractor_id, is_deleted=False).first()
        if not contractor:
            return jsonify({'error': f'Contractor {contractor_id} not found'}), 404
            
        data = request.get_json()
        
        # Validate required fields
        if 'service_id' not in data or 'vehicle_type_id' not in data:
            return jsonify({'error': 'Missing service_id or vehicle_type_id'}), 400
            
        service_id = data['service_id']
        vehicle_type_id = data['vehicle_type_id']
        cost = data.get('cost')
        
        # Validate that cost is non-negative if provided
        if cost is not None and cost < 0:
            return jsonify({'error': 'Cost must be non-negative'}), 400
            
        # Validate vehicle type exists and is active
        from backend.models.vehicle_type import VehicleType
        vehicle_type = VehicleType.query.filter_by(id=vehicle_type_id, is_deleted=False).first()
        if not vehicle_type:
            return jsonify({'error': f'Vehicle type {vehicle_type_id} not found or inactive'}), 400
            
        # Validate service exists and is active
        from backend.models.service import Service
        service = Service.query.filter_by(id=service_id, is_deleted=False).first()
        if not service:
            return jsonify({'error': f'Service {service_id} not found or inactive'}), 400
            
        # Update the pricing
        pricing = ContractorServicePricingService.update_pricing(
            contractor_id, service_id, vehicle_type_id, cost
        )
        
        result = {
            'id': pricing.id,
            'contractor_id': pricing.contractor_id,
            'service_id': pricing.service_id,
            'vehicle_type_id': pricing.vehicle_type_id,
            'service_name': pricing.service.name if pricing.service else None,
            'vehicle_type_name': pricing.vehicle_type.name if pricing.vehicle_type else None,
            'cost': pricing.cost
        }
        
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Unhandled error in update_contractor_pricing_by_vehicle_type: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
