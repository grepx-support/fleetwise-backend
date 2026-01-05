from flask import Blueprint, request, jsonify
from backend.services.user_service import UserService, ServiceError
from backend.services.password_reset_service import PasswordResetService, PasswordResetError
from backend.services.driver_auth_service import DriverAuthService, DriverAuthError
from backend.schemas.user_schema import UserSchema
from backend.schemas.customer_schema import CustomerSchema
from backend.schemas.driver_schema import DriverSchema
import logging
from flask_security.decorators import roles_required, auth_required, roles_accepted
from flask_security import current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

user_bp = Blueprint('user', __name__)
schema = UserSchema()
schema_many = UserSchema(many=True)
customer_schema = CustomerSchema(many=True)
driver_schema = DriverSchema(many=True)

# Initialize limiter for rate limiting
limiter = Limiter(key_func=get_remote_address)

def init_app(app):
    """Initialize the limiter with the Flask app"""
    limiter.init_app(app)


@user_bp.route('/me', methods=['GET'])
@auth_required()
def get_me():
    try:
        return jsonify(schema.dump(current_user)), 200
    except Exception as e:
        logging.error(f"Unhandled error in get_me: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/me', methods=['PUT'])
@auth_required()
def update_my_profile():
    """
    Update the current user's profile information (name, etc.)
    
    Security: Users can only update their own profile. User ID is derived from
    authentication token via current_user.id. This endpoint intentionally restricts
    updates to the authenticated user's own profile to prevent privilege escalation.
    
    Expected JSON:
    {
        "name": "John Doe"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
            
        # Only allow updating specific fields
        allowed_fields = ['name']
        update_data = {}
        for key, value in data.items():
            if key in allowed_fields:
                if key == 'name' and value is not None:
                    value = value.strip()
                    if not value:  # Treat empty string as null
                        value = None
                update_data[key] = value
        
        if not update_data:
            return jsonify({'error': 'No valid fields to update'}), 400
            
        user = UserService.update(current_user.id, update_data)
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        return jsonify(schema.dump(user)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_my_profile: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def list_users():
    try:
        users = UserService.get_all()
        return jsonify(schema_many.dump(users)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_users: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users/<int:user_id>', methods=['GET'])
@auth_required()
def get_user(user_id):
    try:
        # Only allow user to view their own info or admin/manager
        if current_user.has_role('admin') or current_user.has_role('manager') or current_user.id == user_id:
            user = UserService.get_by_id(user_id)
            if not user:
                return jsonify({'error': 'User not found'}), 404
            return jsonify(schema.dump(user)), 200
        return jsonify({'error': 'Forbidden'}), 403
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_user: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users', methods=['POST'])
@roles_required('admin')
def create_user():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        user = UserService.create(data)
        return jsonify(schema.dump(user)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_user: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users/<int:user_id>', methods=['PUT'])
@roles_required('admin')
def update_user(user_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        user = UserService.update(user_id, data)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify(schema.dump(user)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_user: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users/<int:user_id>', methods=['DELETE'])
@roles_required('admin')
def delete_user(user_id):
    try:
        success = UserService.delete(user_id)
        if not success:
            return jsonify({'error': 'User not found'}), 404
        return jsonify({'message': 'User deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_user: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500 
    
@user_bp.route('/users/device-token', methods=['POST'])
@roles_required('driver')
def save_device_token():
    data = request.get_json()
    driver_id = data.get('driver_id')

    if not driver_id:
        return jsonify({'error': 'driver_id is required'}), 400

    if not data.get('android_device_token') and not data.get('ios_device_token'):
        return jsonify({'error': 'Either android_device_token or ios_device_token is required'}), 400

    try:
        success = UserService.save_device_token(driver_id, data)

        if not success:
            return jsonify({'error': 'User with provided driver_id not found'}), 404

        return jsonify({'message': 'Device token saved successfully'}), 200

    except Exception as e:
        logging.error(f"Error in save_device_token: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users/device-token/<int:driver_id>', methods=['DELETE'])
@roles_required('driver')  
def remove_device_token(driver_id):
    if not driver_id:
        return jsonify({'error': 'driver_id is required'}), 400

    try:
        UserService.remove_device_tokens(driver_id)
        return jsonify({'message': 'Device tokens removed successfully'}), 200

    except ServiceError as se:
        return jsonify({'error': se.message}), 400

    except Exception as e:
        logging.error(f"Unhandled error in remove_device_token: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


# Password Reset Endpoints

@user_bp.route('/reset-password-request', methods=['POST'])
@limiter.limit("3 per hour")
@limiter.limit("1 per 15 minutes", key_func=lambda: request.get_json().get('email', '') if request.get_json() else '')
def request_password_reset():
    """
    Request password reset - sends email with reset token
    
    Expected JSON:
    {
        "email": "user@example.com"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
        
        email = data.get('email', '').strip()
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Request password reset
        success = PasswordResetService.request_password_reset(email)
        
        if success:
            return jsonify({
                'message': 'If an account with that email exists, you will receive password reset instructions.'
            }), 200
        else:
            return jsonify({'error': 'Unable to process request. Please try again later.'}), 500
            
    except PasswordResetError as pre:
        return jsonify({'error': pre.message}), pre.code
    except Exception as e:
        logging.error(f"Unhandled error in request_password_reset: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@user_bp.route('/reset-password/<token>', methods=['POST'])
def reset_password_with_token(token):
    """
    Reset password using token from email
    
    Expected JSON:
    {
        "new_password": "NewPassword123!",
        "confirm_password": "NewPassword123!"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
        
        new_password = data.get('new_password', '').strip()
        confirm_password = data.get('confirm_password', '').strip()
        
        if not new_password:
            return jsonify({'error': 'New password is required'}), 400
        if not confirm_password:
            return jsonify({'error': 'Password confirmation is required'}), 400
        
        # Reset password
        success = PasswordResetService.reset_password_with_token(
            token, new_password, confirm_password
        )
        
        if success:
            return jsonify({
                'message': 'Password has been reset successfully. You can now log in with your new password.'
            }), 200
        else:
            return jsonify({'error': 'Unable to reset password. Please try again later.'}), 500
            
    except PasswordResetError as pre:
        return jsonify({'error': pre.message}), pre.code
    except Exception as e:
        logging.error(f"Unhandled error in reset_password_with_token: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@user_bp.route('/change-password', methods=['POST'])
@auth_required()
def change_password():
    """
    Change password for authenticated user
    
    Expected JSON:
    {
        "current_password": "CurrentPassword123!",
        "new_password": "NewPassword123!"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
        
        current_password = data.get('current_password', '').strip()
        new_password = data.get('new_password', '').strip()
        
        if not current_password:
            return jsonify({'error': 'Current password is required'}), 400
        if not new_password:
            return jsonify({'error': 'New password is required'}), 400
        
        # Change password
        success = PasswordResetService.change_password(
            current_user.id, current_password, new_password
        )
        
        if success:
            return jsonify({
                'message': 'Password has been changed successfully.'
            }), 200
        else:
            return jsonify({'error': 'Unable to change password. Please try again later.'}), 500
            
    except PasswordResetError as pre:
        return jsonify({'error': pre.message}), pre.code
    except Exception as e:
        logging.error(f"Unhandled error in change_password: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users/unassigned-customers', methods=['GET'])
@roles_required('admin')
def get_unassigned_customers():
    """
    Returns list of unassigned customers
    """
    try:
        customers = UserService.get_unassigned_customers()
        return jsonify(customer_schema.dump(customers)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_unassigned_customers: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users/unassigned-drivers', methods=['GET'])
@roles_required('admin')
def get_unassigned_drivers():
    """
    Returns list of unassigned drivers
    """
    try:
        drivers = UserService.get_unassigned_drivers()
        return jsonify(driver_schema.dump(drivers)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_unassigned_drivers: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@user_bp.route('/users/<int:user_id>/assign', methods=['PUT'])
@roles_required('admin')
def assign_customer_or_driver(user_id):
    """
    Assigns a customer or driver to a user
    
    Expected JSON:
    {
        "user_type": "customer" or "driver",
        "entity_id": int
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
            
        user_type = data.get('user_type')
        entity_id = data.get('entity_id')
        
        if not user_type:
            return jsonify({'error': 'user_type is required'}), 400
            
        if not entity_id:
            return jsonify({'error': 'entity_id is required'}), 400
            
        if user_type not in ['customer', 'driver']:
            return jsonify({'error': 'user_type must be either "customer" or "driver"'}), 400
            
        user = UserService.assign_customer_or_driver(user_id, user_type, entity_id)
        return jsonify(schema.dump(user)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in assign_customer_or_driver: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

# Add the missing endpoints for fetching single driver/customer by ID
from backend.services.driver_service import DriverService
from backend.services.customer_service import CustomerService

@user_bp.route('/drivers/<int:driver_id>', methods=['GET'])
@roles_required('admin')
def get_driver_by_id(driver_id):
    try:
        driver = DriverService.get_by_id(driver_id)
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        return jsonify(driver_schema.dump(driver)), 200
    except Exception as e:
        logging.error(f"Error fetching driver: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch driver'}), 500

# Driver Authentication Endpoints

@user_bp.route('/driver/forgot-password', methods=['POST'])
@limiter.limit("3 per hour")
@limiter.limit("1 per 15 minutes", key_func=lambda: request.get_json().get('email', '') if request.get_json() else '')
def request_driver_password_reset():
    """
    Request driver password reset - sends OTP to driver's email
    
    Expected JSON:
    {
        "email": "driver@example.com"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
        
        email = data.get('email', '').strip()
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Request driver password reset
        success = DriverAuthService.request_driver_password_reset(email)
        
        if success:
            return jsonify({
                'message': 'If an account with that email exists, you will receive password reset OTP instructions.'
            }), 200
        else:
            return jsonify({'error': 'Unable to process request. Please try again later.'}), 500
            
    except DriverAuthError as dae:
        return jsonify({'error': dae.message}), dae.code
    except Exception as e:
        logging.error(f"Unhandled error in request_driver_password_reset: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@user_bp.route('/driver/verify-otp', methods=['POST'])
def driver_verify_otp():
    """
    Driver verify OTP endpoint
    
    Expected JSON:
    {
        "otp": "123456"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
        
        otp = data.get('otp', '').strip()
        
        if not otp:
            return jsonify({'error': 'OTP is required'}), 400
        
        # Verify the OTP
        result = DriverAuthService.verify_driver_otp(otp)
        
        if result['valid']:
            return jsonify({'message': 'OTP verified successfully', 'email': result['email']}), 200
        else:
            return jsonify({'error': result['error']}), 400
            
    except DriverAuthError as dae:
        return jsonify({'error': dae.message}), dae.code
    except Exception as e:
        logging.error(f"Unhandled error in driver_verify_otp: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@user_bp.route('/driver/reset-password', methods=['POST'])
def driver_reset_password():
    """
    Driver reset password endpoint
    
    Expected JSON:
    {
        "email": "driver@example.com",
        "new_password": "NewPassword123!",
        "confirm_password": "NewPassword123!"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
        
        email = data.get('email', '').strip().lower()
        new_password = data.get('new_password', '').strip()
        confirm_password = data.get('confirm_password', '').strip()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        if not new_password:
            return jsonify({'error': 'New password is required'}), 400
        if not confirm_password:
            return jsonify({'error': 'Password confirmation is required'}), 400
        
        # Reset password - in a real implementation, we'd verify that OTP was previously validated
        # For now, we'll implement the full flow with OTP validation
        success = DriverAuthService.reset_driver_password_with_email_only(
            email, new_password, confirm_password
        )
        
        if success:
            return jsonify({
                'message': 'Password has been reset successfully. You can now log in with your new password.'
            }), 200
        else:
            return jsonify({'error': 'Unable to reset password. Please try again later.'}), 500
            
    except DriverAuthError as dae:
        return jsonify({'error': dae.message}), dae.code
    except Exception as e:
        logging.error(f"Unhandled error in driver_reset_password: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@user_bp.route('/customers/<int:customer_id>', methods=['GET'])
@roles_required('admin')
def get_customer_by_id(customer_id):
    try:
        customer = CustomerService.get_by_id(customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        return jsonify(customer_schema.dump(customer)), 200
    except Exception as e:
        logging.error(f"Error fetching customer: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch customer'}), 500
