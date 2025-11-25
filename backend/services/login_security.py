"""
Login security handlers for account lockout and failed login tracking
"""
import logging
from flask import request, jsonify, g
from flask_security import user_authenticated
from backend.extensions import db
from backend.models.user import User

logger = logging.getLogger(__name__)


def init_login_security(app):
    """Initialize login security handlers"""

    @app.before_request
    def check_account_lockout():
        """Check if account is locked before processing login"""
        # Only check for login endpoint
        if request.endpoint and 'login' in request.endpoint.lower():
            # Get email from request
            if request.is_json:
                data = request.get_json(silent=True)
            else:
                data = request.form

            if not data:
                return None

            email = data.get('email')
            if not email:
                return None

            # Find user by email
            user = User.query.filter_by(email=email).first()
            if not user:
                return None

            # Try to unlock if lock has expired
            if hasattr(user, 'unlock_if_expired'):
                if user.unlock_if_expired():
                    db.session.commit()
                    logger.info(f"Account lock expired and removed for: {email}")

            # Check if account is still locked
            if hasattr(user, 'is_account_locked') and user.is_account_locked():
                locked_until = user.locked_until.strftime('%Y-%m-%d %H:%M:%S') if user.locked_until else 'unknown'
                logger.warning(f"Blocked login attempt for locked account: {email} (locked until: {locked_until})")

                return jsonify({
                    'response': {
                        'errors': ['Account is locked due to multiple failed login attempts. Please try again later or contact support.'],
                        'locked_until': locked_until
                    }
                }), 403

        return None

    @user_authenticated.connect_via(app)
    def on_user_authenticated(sender, user, **extra):
        """Handle successful login - reset failed attempts"""
        try:
            # Reset failed login attempts on successful login
            if hasattr(user, 'reset_failed_login_attempts'):
                user.reset_failed_login_attempts()
                db.session.commit()
                logger.info(f"User {user.email} logged in successfully. Reset failed login attempts.")
        except Exception as e:
            logger.error(f"Error resetting failed login attempts: {e}")
            db.session.rollback()

    @app.after_request
    def track_failed_login(response):
        """Track failed login attempts by checking response status"""
        try:
            # Only process login endpoint responses
            if not request.endpoint or 'login' not in request.endpoint.lower():
                return response

            # Check if login failed (401 Unauthorized or 400 Bad Request)
            if response.status_code not in [400, 401]:
                return response

            # Get email from request
            if request.is_json:
                data = request.get_json(silent=True)
            else:
                data = request.form

            if not data:
                return response

            email = data.get('email')
            if not email:
                return response

            # Find user by email
            user = User.query.filter_by(email=email).first()
            if not user:
                # Don't reveal if user exists or not (security best practice)
                logger.warning(f"Failed login attempt for non-existent user: {email}")
                return response

            # Try to unlock if lock has expired before recording failed attempt
            if hasattr(user, 'unlock_if_expired'):
                if user.unlock_if_expired():
                    db.session.commit()
                    logger.info(f"Account lock expired and removed for: {email}")

            # Check if account is still locked
            if hasattr(user, 'is_account_locked') and user.is_account_locked():
                logger.warning(f"Login attempt for locked account: {email}")
                return response

            # Record failed login attempt
            if hasattr(user, 'record_failed_login'):
                user.record_failed_login()
                db.session.commit()

                logger.warning(
                    f"Failed login attempt for {email}. "
                    f"Attempts: {user.failed_login_attempts}/5"
                )

                # Check if account just got locked
                if user.is_account_locked():
                    logger.error(f"Account locked for {email} due to multiple failed login attempts")

        except Exception as e:
            logger.error(f"Error recording failed login attempt: {e}")
            db.session.rollback()

        return response
