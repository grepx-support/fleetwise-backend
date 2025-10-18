import logging
from flask import Blueprint, jsonify
from backend.services.password_reset_service import PasswordResetService
from flask_security import roles_required

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/cleanup-expired-tokens', methods=['POST'])
@roles_required('admin')
def cleanup_expired_tokens():
    """
    Admin endpoint to manually cleanup expired password reset tokens
    
    Returns:
        JSON response with cleanup results
    """
    try:
        cleaned_count = PasswordResetService.cleanup_expired_tokens()
        
        return jsonify({
            'message': f'Successfully cleaned up {cleaned_count} expired tokens',
            'tokens_cleaned': cleaned_count
        }), 200
        
    except Exception as e:
        logging.error(f"Error in cleanup_expired_tokens: {e}", exc_info=True)
        return jsonify({'error': 'Unable to cleanup expired tokens'}), 500