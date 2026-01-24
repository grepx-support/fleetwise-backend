import logging
import queue
import threading
import os
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from flask import current_app, render_template_string
from flask_mail import Message
from flask_security.utils import hash_password, verify_password
from cryptography.fernet import Fernet

from backend.extensions import db, mail
from backend.models.user import User
from backend.models.password_reset_token import PasswordResetToken
from backend.models.settings import UserSettings
from backend.models.password_history import PasswordHistory
from backend.utils.validation import (
    validate_password_change_data,
    validate_password_reset_request_data,
    validate_password_reset_data,
    validate_password_strength,
    validate_admin_password_change_data
)

# Add the import for ThreadPoolExecutor and FutureTimeoutError
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError


# Module-level thread pool for email sending
email_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="email-sender")


class PasswordResetError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message = message
        self.code = code


def get_admin_email_settings() -> Dict[str, Any]:
    """
    Fetch email settings from admin panel (UserSettings.preferences.email_settings)

    Returns:
        dict: Email configuration with keys:
            - smtp_host: SMTP server hostname
            - smtp_port: SMTP port number
            - use_tls: Whether to use TLS
            - use_ssl: Whether to use SSL
            - username: SMTP username
            - password: SMTP password (decrypted)
            - sender_email: Default sender email

    Raises:
        ValueError: If email settings are not configured in admin panel
    """
    try:
        # Get the first admin user's settings
        settings = UserSettings.query.first()

        if not settings or not settings.preferences:
            raise ValueError("Email settings not found. Please configure email settings in the admin panel.")

        prefs = dict(settings.preferences)
        email_settings = prefs.get('email_settings', {})

        if not email_settings or not email_settings.get('smtp_host'):
            raise ValueError("Email SMTP settings not configured. Please configure email settings in the admin panel.")

        # Decrypt password if encrypted
        password = email_settings.get('password', '')
        if password:
            try:
                encryption_key = current_app.config.get('EMAIL_PASSWORD_KEY')
                if encryption_key:
                    f = Fernet(encryption_key.encode())
                    try:
                        decrypted_password = f.decrypt(password.encode()).decode()
                        password = decrypted_password
                    except Exception as decrypt_error:
                        logging.error(f"Password decryption failed: {decrypt_error}")
                        raise ValueError("Email password decryption failed. Please reconfigure email settings in the admin panel.")
            except ValueError:
                raise
            except Exception as e:
                logging.error(f"Error processing email password: {e}")
                raise ValueError("Error processing email password. Please reconfigure email settings in the admin panel.")

        # Validate required fields
        if not email_settings.get('username'):
            raise ValueError("Email username not configured. Please configure email settings in the admin panel.")

        if not password:
            raise ValueError("Email password not configured. Please configure email settings in the admin panel.")

        # Return admin panel settings
        return {
            'smtp_host': email_settings.get('smtp_host'),
            'smtp_port': int(email_settings.get('smtp_port', 587)),
            'use_tls': email_settings.get('use_tls', True),
            'use_ssl': email_settings.get('use_ssl', False),
            'username': email_settings.get('username'),
            'password': password,
            'sender_email': email_settings.get('sender_email', 'noreply@fleetwise.com')
        }

    except ValueError:
        raise
    except Exception as e:
        logging.error(f"Error fetching admin panel email settings: {e}")
        raise ValueError("Unable to fetch email settings. Please configure email settings in the admin panel.")


class PasswordResetService:
    """Service for handling password reset and change operations"""
    
    @staticmethod
    def request_password_reset(email: str) -> bool:
        """
        Initiate password reset process by sending reset email
        
        Args:
            email: User's email address
            
        Returns:
            bool: True if email was sent successfully (even if user doesn't exist for security)
        
        Raises:
            PasswordResetError: If there's an issue with the email sending process
        """
        try:
            # Validate email format
            is_valid, errors = validate_password_reset_request_data({'email': email})
            if not is_valid:
                raise PasswordResetError(f"Invalid email: {errors['email'][0]}")
            
            email = email.strip().lower()
            
            # Find user by email
            user = User.query.filter_by(email=email).first()
            
            # For security reasons, always return success even if user doesn't exist
            # This prevents email enumeration attacks
            if not user:
                logging.warning(f"Password reset requested for non-existent email: {email}")
                return True
            
            if not user.active:
                logging.warning(f"Password reset requested for inactive user: {email}")
                return True
            
            # Clean up any existing tokens for this user
            PasswordResetToken.query.filter_by(user_id=user.id).delete()
            
            # Create new reset token
            token, raw_token = PasswordResetToken.create_token(
                user.id, 
                current_app.config.get('PASSWORD_RESET_TOKEN_EXPIRY_HOURS', 1)
            )            
            # Save token to database first, regardless of email outcome
            db.session.add(token)
            db.session.commit()
            
            # Generate reset link - using the correct frontend route
            frontend_url = current_app.config.get('FRONTEND_URL')
            reset_link = f"{frontend_url}/reset-password/{raw_token}"
            
            # Attempt email delivery without affecting token validity
            try:
                email_sent = PasswordResetService._send_reset_email_threaded(user, reset_link)
                
                if not email_sent:
                    logging.warning(f"Email failed but token persisted for debugging: {raw_token}")
                    # For development, we can still return True to allow testing
                    # In production, you might want to handle this differently
                else:
                    logging.info(f"Password reset email sent successfully to {email}")
            except Exception as email_error:
                logging.error(f"Email error, token remains valid: {email_error}", exc_info=True)
            
            # Always return True for security reasons (prevent email enumeration)
            # But for development/debugging, we can log the actual status
            return True
            
        except PasswordResetError:
            raise
        except Exception as e:
            # Only rollback if there's an error before token commit
            # If we reach here, it's likely a validation or database error before commit
            db.session.rollback()
            logging.error(f"Error in request_password_reset: {e}", exc_info=True)
            raise PasswordResetError("Unable to process password reset request. Please try again later.", 500)
    
    @staticmethod
    def reset_password_with_token(token: str, new_password: str, confirm_password: str) -> bool:
        """
        Reset password using a valid token
        
        Args:
            token: Password reset token
            new_password: New password
            confirm_password: Password confirmation
            
        Returns:
            bool: True if password was reset successfully
            
        Raises:
            PasswordResetError: If token is invalid or password validation fails
        """
        try:
            # Validate password data
            data = {
                'new_password': new_password,
                'confirm_password': confirm_password
            }
            is_valid, errors = validate_password_reset_data(data)
            if not is_valid:
                error_messages = []
                for field, field_errors in errors.items():
                    error_messages.extend(field_errors)
                raise PasswordResetError(f"Password validation failed: {'; '.join(error_messages)}")
            
            # Verify and consume token atomically to prevent race conditions
            reset_token = PasswordResetToken.verify_and_consume_token(token)
            if not reset_token:
                raise PasswordResetError("Invalid or expired reset token.", 400)
            
            # Get user
            user = User.query.get(reset_token.user_id)
            if not user or not user.active:
                raise PasswordResetError("User account not found or inactive.", 400)

            # Check for password reuse
            recent_passwords = PasswordHistory.get_recent_passwords(user.id, 5)
            for old_password_hash in recent_passwords:
                if verify_password(new_password, old_password_hash):
                    raise PasswordResetError("Cannot reuse any of your last 5 passwords.", 400)

            # Update password
            hashed_password = hash_password(new_password)
            user.password = hashed_password

            # Add to password history
            PasswordHistory.add_to_history(user.id, hashed_password)

            # Commit changes
            db.session.commit()

            # Send password reset confirmation email
            logging.info(f"Attempting to send password reset confirmation email to {user.email}")
            email_sent = PasswordResetService._send_password_reset_confirmation_email(user)
            if email_sent:
                logging.info(f"Password reset confirmation email sent successfully to {user.email}")
            else:
                logging.error(f"Failed to send password reset confirmation email to {user.email}")

            logging.info(f"Password reset successful for user {user.email}")
            return True
            
        except PasswordResetError:
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in reset_password_with_token: {e}", exc_info=True)
            raise PasswordResetError("Unable to reset password. Please try again later.", 500)
    
    @staticmethod
    def change_password(user_id: int, current_password: str, new_password: str) -> bool:
        """
        Change password for authenticated user
        
        Args:
            user_id: ID of the authenticated user
            current_password: User's current password
            new_password: New password
            
        Returns:
            bool: True if password was changed successfully
            
        Raises:
            PasswordResetError: If validation fails or current password is incorrect
        """
        try:
            # Validate input data
            data = {
                'current_password': current_password,
                'new_password': new_password
            }
            is_valid, errors = validate_password_change_data(data)
            if not is_valid:
                error_messages = []
                for field, field_errors in errors.items():
                    error_messages.extend(field_errors)
                raise PasswordResetError(f"Validation failed: {'; '.join(error_messages)}")
            
            # Get user
            user = User.query.get(user_id)
            if not user or not user.active:
                raise PasswordResetError("User account not found or inactive.", 400)
            
            # Verify current password
            if not verify_password(current_password, user.password):
                raise PasswordResetError("Current password is incorrect.", 400)

            # Check for password reuse
            recent_passwords = PasswordHistory.get_recent_passwords(user_id, 5)
            for old_password_hash in recent_passwords:
                if verify_password(new_password, old_password_hash):
                    raise PasswordResetError("Cannot reuse any of your last 5 passwords.", 400)

            # Update password
            hashed_password = hash_password(new_password)
            user.password = hashed_password

            # Add to password history
            PasswordHistory.add_to_history(user_id, hashed_password)

            # Commit changes
            db.session.commit()
            
            # Send password change confirmation email
            PasswordResetService._send_password_change_confirmation_email(user)
            
            logging.info(f"Password changed successfully for user {user.email}")
            return True
            
        except PasswordResetError:
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in change_password: {e}", exc_info=True)
            raise PasswordResetError("Unable to change password. Please try again later.", 500)
    
    @staticmethod
    def admin_change_password(user_id: int, new_password: str) -> bool:
        """
        Admin function to change any user's password
        
        Args:
            user_id: ID of the user whose password to change
            new_password: New password
            
        Returns:
            bool: True if password was changed successfully
            
        Raises:
            PasswordResetError: If validation fails or user not found
        """
        try:
            # Validate input data using admin-specific validation
            # Create a temporary structure to validate the password
            temp_validation_data = {
                'new_password': new_password,
                'confirm_password': new_password  # We validate strength, not equality with current
            }
            is_valid, errors = validate_admin_password_change_data(temp_validation_data)
            if not is_valid:
                error_messages = []
                # Collect only new_password related errors
                for field, field_errors in errors.items():
                    if field == 'new_password':
                        error_messages.extend(field_errors)
                if error_messages:
                    raise PasswordResetError(f"Validation failed: {'; '.join(error_messages)}")
            
            # Get user
            user = User.query.get(user_id)
            if not user or not user.active:
                raise PasswordResetError("User account not found or inactive.", 400)

            # Check for password reuse
            recent_passwords = PasswordHistory.get_recent_passwords(user_id, 5)
            for old_password_hash in recent_passwords:
                if verify_password(new_password, old_password_hash):
                    raise PasswordResetError("Cannot reuse any of the last 5 passwords.", 400)

            # Update password
            hashed_password = hash_password(new_password)
            user.password = hashed_password

            # Add to password history
            PasswordHistory.add_to_history(user_id, hashed_password)

            # Commit changes
            db.session.commit()
            
            # Send password change confirmation email
            PasswordResetService._send_password_change_confirmation_email(user)
            
            logging.info(f"Password changed successfully for user {user.email} by admin")
            return True
            
        except PasswordResetError:
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in admin_change_password: {e}", exc_info=True)
            raise PasswordResetError("Unable to change password. Please try again later.", 500)
    
    @staticmethod
    def cleanup_expired_tokens() -> int:
        """
        Clean up expired and used tokens from database
        
        Returns:
            int: Number of tokens cleaned up
        """
        try:
            count = PasswordResetToken.cleanup_expired_tokens()
            db.session.commit()
            logging.info(f"Cleaned up {count} expired password reset tokens")
            return count
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error cleaning up expired tokens: {e}", exc_info=True)
            return 0

    @staticmethod
    def _send_reset_email_threaded(user: User, reset_link: str) -> bool:
        """
        Send password reset email using admin panel email settings with thread pool executor
        """
        try:
            # Get email configuration from admin panel
            email_config = get_admin_email_settings()

            smtp_server = email_config['smtp_host']
            smtp_port = email_config['smtp_port']
            use_tls = email_config['use_tls']
            use_ssl = email_config['use_ssl']
            smtp_username = email_config['username']
            smtp_password = email_config['password']
            mail_sender = email_config['sender_email']
        except ValueError as e:
            # Email settings not configured
            logging.error(f"Email configuration error: {str(e)}")
            return False

        # Capture user email as string to avoid Flask context issues
        user_email = user.email

        # Get company name from general settings (fallback to FleetWise)
        company_name = "{company_name}"
        try:
            settings = UserSettings.query.first()
            if settings and settings.preferences:
                prefs = dict(settings.preferences)
                general_settings = prefs.get('general_settings', {})
                company_name = general_settings.get('company_name', '{company_name}')
        except Exception as e:
            logging.warning(f"Could not fetch company name from settings: {e}")

        # Debug: Log email config (without password)
        logging.info(f"Using admin panel email config - Server: {smtp_server}, Port: {smtp_port}, Sender: {mail_sender}")

        def send_reset_email_worker(user_email, reset_link, smtp_server, smtp_port, use_tls, use_ssl, smtp_username, smtp_password, mail_sender, company_name):
            """Worker function that runs in background thread"""
            try:
                import smtplib
                import ssl
                import time
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart

                # Create multipart message
                msg = MIMEMultipart('alternative')
                msg['Subject'] = f'{company_name} - Password Reset Request'
                msg['From'] = f"{company_name} Support <{mail_sender}>"
                msg['To'] = user_email
                msg['Reply-To'] = mail_sender

                # Essential email headers
                msg['Date'] = time.strftime('%a, %d %b %Y %H:%M:%S %z', time.gmtime())
                msg['Message-ID'] = f"<reset-{int(time.time())}-{hash(user_email) % 100000}@{mail_sender.split('@')[1]}>"
                msg['X-Mailer'] = f"{company_name} Password Reset System"
                msg['X-Priority'] = "3 (Normal)"
                msg['Importance'] = "Normal"
                msg['MIME-Version'] = "1.0"

                # Sender authentication headers
                msg['X-Original-Sender'] = mail_sender
                msg['Return-Path'] = mail_sender
                msg['Sender'] = mail_sender

                # Content classification headers
                msg['X-Auto-Response-Suppress'] = "All"
                msg['Auto-Submitted'] = "auto-generated"

                # List management (reduces spam score)
                msg['List-Unsubscribe'] = f"<mailto:{mail_sender}?subject=Unsubscribe>"
                msg['List-Unsubscribe-Post'] = "List-Unsubscribe=One-Click"

                # Security and classification
                msg['X-Email-Type'] = "Security-Notification"
                msg['X-Content-Category'] = "Transactional"

                # Create enhanced HTML content with company branding
                html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset Request - {company_name}</title>
    <style>
        body {{ margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; }}
        .email-container {{ max-width: 600px; margin: 0 auto; background: white; }}
        .header {{ background: linear-gradient(135deg, #dc3545, #c82333); color: white; padding: 30px 25px; text-align: center; }}
        .content {{ padding: 30px 25px; line-height: 1.6; color: #333; }}
        .info-section {{ background: #f8f9fa; padding: 20px; margin: 20px 0; border-radius: 8px; border-left: 5px solid #dc3545; }}
        .warning-section {{ background: #fff3cd; padding: 20px; margin: 20px 0; border-radius: 8px; border-left: 5px solid #ffc107; }}
        .footer {{ background: #f8f9fa; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
        .button {{ display: inline-block; padding: 15px 30px; background: #dc3545; color: white; text-decoration: none; border-radius: 5px; font-weight: 600; margin: 20px 0; }}
        h1 {{ margin: 0; font-size: 26px; font-weight: 600; }}
        .brand {{ color: #dc3545; font-weight: 700; }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <h1>🔒 Password Reset Request</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">Secure password reset for your {company_name} account</p>
        </div>
        
        <div class="content">
            <p style="font-size: 16px; margin-bottom: 20px;">Hello,</p>
            
            <p style="font-size: 16px;">We received a request to reset the password for your <span class="brand">{company_name}</span> account: <strong>{user_email}</strong></p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_link}" class="button">[RESET] Reset My Password</a>
            </div>
            
            <div class="info-section">
                <h3 style="margin-top: 0; color: #dc3545;">🔗 Alternative Access</h3>
                <p style="margin: 8px 0;">If the button above doesn't work, copy and paste this link into your browser:</p>
                <p style="word-break: break-all; background: #e9ecef; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 14px;">{reset_link}</p>
            </div>
            
            <div class="warning-section">
                <h3 style="margin-top: 0; color: #856404;">[WARNING] Important Security Information</h3>
                <ul style="margin: 10px 0; color: #856404; padding-left: 20px;">
                    <li><strong>This link will expire in 1 hour</strong> for your security</li>
                    <li><strong>This link can only be used once</strong></li>
                    <li><strong>If you didn't request this password reset</strong>, please ignore this email</li>
                    <li><strong>Never share this link</strong> with anyone</li>
                </ul>
            </div>
            
            <h3 style="color: #dc3545; font-size: 18px; margin: 25px 0 15px 0;">[HELP] Need Help?</h3>
            <p style="font-size: 16px;">If you have any questions or didn't request this password reset, please contact our support team immediately.</p>
            <p style="font-size: 16px;"><strong>Contact:</strong> <a href="mailto:{mail_sender}" style="color: #dc3545; text-decoration: none;">{mail_sender}</a></p>
            
            <div style="margin: 30px 0; text-align: center; padding: 20px; background: #f8f9fa; border-radius: 8px;">
                <p style="font-size: 16px; margin: 0;">Thank you for using <span class="brand">{company_name}</span>.</p>
                <p style="font-size: 16px; margin: 15px 0 0 0;"><strong>Best regards,<br>{company_name} Security Team<br><span class="brand">{company_name}</span></strong></p>
            </div>
        </div>
        
        <div class="footer">
            <p style="margin: 0 0 5px 0;">This is an automated security notification from {company_name}.</p>
            <p style="margin: 0 0 5px 0;">(c) 2024 {company_name}. All rights reserved.</p>
            <p style="margin: 0; font-style: italic;">Please do not reply to this email.</p>
        </div>
    </div>
</body>
</html>
                """
                
                # Create professional text version
                text_content = f"""
{company_name} - Password Reset Request

Hello,

We received a request to reset the password for your {company_name} account: {user_email}

PLEASE CLICK THIS LINK TO RESET YOUR PASSWORD:
{reset_link}

IMPORTANT SECURITY INFORMATION:
- This link will expire in 1 hour for your security
- This link can only be used once
- If you didn't request this password reset, please ignore this email
- Never share this link with anyone

NEED HELP?
If you have any questions or didn't request this password reset, please contact our support team immediately.
Contact: {mail_sender}

Thank you for using {company_name}.

Best regards,
{company_name} Security Team
{company_name}

---
This is an automated security notification from {company_name}.
(c) 2024 {company_name}. All rights reserved.
Please do not reply to this email.
                """
                
                # Attach content parts
                text_part = MIMEText(text_content, 'plain', 'utf-8')
                html_part = MIMEText(html_content, 'html', 'utf-8')
                msg.attach(text_part)
                msg.attach(html_part)

                # Send email using configured SMTP settings
                context = ssl.create_default_context()

                if use_ssl:
                    # Use SMTP_SSL for SSL connections (port 465)
                    with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30, context=context) as server:
                        server.login(smtp_username, smtp_password)
                        result = server.send_message(msg)
                        return not bool(result)  # Empty dict means success
                else:
                    # Use regular SMTP with optional STARTTLS (port 587 or 25)
                    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                        if use_tls:
                            server.starttls(context=context)
                        server.login(smtp_username, smtp_password)
                        result = server.send_message(msg)
                        return not bool(result)  # Empty dict means success

            except Exception as e:
                # Log the error and return False
                logging.error(f"Password reset email error: {str(e)}")
                return False

        # Submit the email sending task to the thread pool executor
        try:
            future = email_executor.submit(
                send_reset_email_worker,
                user_email, reset_link, smtp_server, smtp_port,
                use_tls, use_ssl, smtp_username, smtp_password, mail_sender, company_name
            )
            return future.result(timeout=30)  # Increased timeout to 30 seconds for reliable email delivery
        except FutureTimeoutError:
            logging.error("Password reset email sending timeout after 30 seconds")
            return False
        except Exception as e:
            logging.error(f"Password reset email sending failed: {str(e)}")
            return False

    @staticmethod
    def _send_password_reset_confirmation_email(user: User) -> bool:
        """
        Send confirmation email after successful password reset using admin panel email settings with thread pool executor
        """
        try:
            # Get email configuration from admin panel
            logging.info("Fetching email configuration for password reset confirmation")
            email_config = get_admin_email_settings()

            smtp_server = email_config['smtp_host']
            smtp_port = email_config['smtp_port']
            use_tls = email_config['use_tls']
            use_ssl = email_config['use_ssl']
            smtp_username = email_config['username']
            smtp_password = email_config['password']
            mail_sender = email_config['sender_email']

            logging.info(f"Email config - SMTP: {smtp_server}:{smtp_port}, User: {smtp_username}, Sender: {mail_sender}")

            # Capture user email as string to avoid Flask context issues
            user_email = user.email

            # Get company name from general settings (fallback to FleetWise)
            company_name = "FleetWise"
            try:
                settings = UserSettings.query.first()
                if settings and settings.preferences:
                    prefs = dict(settings.preferences)
                    general_settings = prefs.get('general_settings', {})
                    company_name = general_settings.get('company_name', 'FleetWise')
            except Exception as e:
                logging.warning(f"Could not fetch company name from settings: {e}")

            def send_confirmation_email_worker(user_email, smtp_server, smtp_port, use_tls, use_ssl, smtp_username, smtp_password, mail_sender, company_name):
                """Worker function that runs in background thread using only Zoho"""
                try:
                    import smtplib
                    import ssl
                    import time
                    from email.mime.text import MIMEText
                    from email.mime.multipart import MIMEMultipart
                    from datetime import datetime
                    
                    # Create multipart message with proper headers
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = '🔒 Password Updated Successfully - {company_name} Security Alert'
                    msg['From'] = f"{company_name} Security <{mail_sender}>"
                    msg['To'] = user_email
                    msg['Reply-To'] = mail_sender

                    # Essential email headers
                    msg['Date'] = time.strftime('%a, %d %b %Y %H:%M:%S %z', time.gmtime())
                    msg['Message-ID'] = f"<fleetwise-{int(time.time())}-{hash(user_email) % 100000}@{mail_sender.split('@')[1]}>"
                    msg['X-Mailer'] = "{company_name}"
                    msg['MIME-Version'] = "1.0"

                    # Priority headers for notifications (IMPORTANT: Changed to High Priority)
                    msg['X-Priority'] = "1 (Highest)"
                    msg['Priority'] = "urgent"
                    msg['Importance'] = "high"

                    # Sender authentication headers
                    msg['Return-Path'] = mail_sender

                    # Mark as transactional (not promotional) to avoid spam
                    msg['Precedence'] = "bulk"
                    msg['X-Content-Category'] = "Transactional"
                    msg['X-Email-Type'] = "Account-Security-Notification"
                    
                    # Get current timestamp
                    current_time = datetime.now().strftime("%B %d, %Y at %I:%M %p")
                    
                    # Professional text content
                    text_content = f"""
Password Reset Successful - {company_name} Account Security

Dear Valued Customer,

This email confirms that your {company_name} account password has been successfully updated on {current_time}.

ACCOUNT SECURITY CONFIRMATION:
Account Email: {user_email}
Update Timestamp: {current_time}
Security Status: Password Successfully Updated
Authentication: Verified Secure Connection

SECURITY NOTIFICATION:
Your {company_name} account is now protected with your new password. If you did not initiate this password reset, please contact our security team immediately at {mail_sender}.

ACCOUNT ACCESS:
You can now log in to {company_name} using your new password credentials. We recommend enabling two-factor authentication for enhanced account security.

SECURITY RECOMMENDATIONS:
- Use a strong, unique password for your {company_name} account
- Never share your login credentials with anyone
- Keep your password confidential and secure
- Monitor your account for any suspicious activity
- Enable two-factor authentication when available

SUPPORT ASSISTANCE:
If you have any questions or need assistance, our support team is available 24/7.
Contact: {mail_sender}
Website: https://fleetwise.grepx.co.in

Thank you for using {company_name}.

Best regards,
{company_name} Security Team
{company_name}

---
This is an automated security notification from {company_name}.
You received this email because a password reset was completed on your account.
(c) 2024 {company_name}. All rights reserved.

If you believe this email was sent in error, please contact our support team immediately.
                    """
                    
                    # Enhanced HTML content with GREPX branding
                    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset Successful - {company_name}</title>
    <style>
        body {{ margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; }}
        .email-container {{ max-width: 600px; margin: 0 auto; background: white; }}
        .header {{ background: linear-gradient(135deg, #2c5aa0, #1a4780); color: white; padding: 30px 25px; text-align: center; }}
        .content {{ padding: 30px 25px; line-height: 1.6; color: #333; }}
        .info-section {{ background: #f8f9fa; padding: 20px; margin: 20px 0; border-radius: 8px; border-left: 5px solid #2c5aa0; }}
        .security-section {{ background: #d4edda; padding: 20px; margin: 20px 0; border-radius: 8px; border-left: 5px solid #28a745; }}
        .footer {{ background: #f8f9fa; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
        h1 {{ margin: 0; font-size: 26px; font-weight: 600; }}
        .highlight {{ color: #2c5aa0; font-weight: 600; }}
        .status-badge {{ background: #28a745; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
        .brand {{ color: #2c5aa0; font-weight: 700; }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <h1>[SECURE] Password Updated Successfully</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">Your {company_name} account is now secure</p>
        </div>
        
        <div class="content">
            <p style="font-size: 16px; margin-bottom: 20px;">Dear Valued Customer,</p>
            
            <p style="font-size: 16px;">This email confirms that your <span class="brand">{company_name}</span> account password has been <span class="highlight">successfully updated</span> on <strong>{current_time}</strong>.</p>
            
            <div class="info-section">
                <h3 style="margin-top: 0; color: #2c5aa0;">[INFO] Account Security Confirmation</h3>
                <p style="margin: 8px 0;"><strong>Account Email:</strong> {user_email}</p>
                <p style="margin: 8px 0;"><strong>Update Time:</strong> {current_time}</p>
                <p style="margin: 8px 0;"><strong>Security Status:</strong> <span class="status-badge">Password Updated</span></p>
                <p style="margin: 8px 0;"><strong>Authentication:</strong> Verified Secure Connection</p>
            </div>
            
            <div class="security-section">
                <h3 style="margin-top: 0; color: #155724;">[CONFIRMED] Security Confirmation</h3>
                <p style="margin: 8px 0; color: #155724;">Your <span class="brand">{company_name}</span> account is now protected with your new password credentials.</p>
                <p style="margin: 8px 0; color: #155724;"><strong>Important:</strong> If you did not initiate this password reset, please contact our security team immediately.</p>
            </div>
            
            <h3 style="color: #2c5aa0; font-size: 18px; margin: 25px 0 15px 0;">[ACCESS] Account Access</h3>
            <p style="font-size: 16px;">You can now log in to <span class="brand">{company_name}</span> using your new password credentials. We recommend enabling two-factor authentication for enhanced account security.</p>
            
            <h3 style="color: #2c5aa0; font-size: 18px; margin: 25px 0 15px 0;">[SUPPORT] Support Assistance</h3>
            <p style="font-size: 16px;">If you have any questions or need assistance, our support team is available 24/7.</p>
            <p style="font-size: 16px;"><strong>Contact:</strong> <a href="mailto:{mail_sender}" style="color: #2c5aa0; text-decoration: none;">{mail_sender}</a></p>
            
            <div style="margin: 30px 0; text-align: center; padding: 20px; background: #f8f9fa; border-radius: 8px;">
                <p style="font-size: 16px; margin: 0;">Thank you for using <span class="brand">{company_name}</span>.</p>
                <p style="font-size: 16px; margin: 15px 0 0 0;"><strong>Best regards,<br>{company_name} Security Team<br><span class="brand">{company_name}</span></strong></p>
            </div>
        </div>
        
        <div class="footer">
            <p style="margin: 0 0 5px 0;">This is an automated security notification from {company_name}.</p>
            <p style="margin: 0 0 5px 0;">(c) 2024 {company_name}. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
                    """
                    
                    # Attach content parts
                    text_part = MIMEText(text_content, 'plain', 'utf-8')
                    html_part = MIMEText(html_content, 'html', 'utf-8')
                    msg.attach(text_part)
                    msg.attach(html_part)

                    # Send email using configured SMTP settings
                    context = ssl.create_default_context()

                    if use_ssl:
                        # Use SMTP_SSL for SSL connections (port 465)
                        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30, context=context) as server:
                            server.login(smtp_username, smtp_password)
                            server.sendmail(from_addr=mail_sender, to_addrs=[user_email], msg=msg.as_string())
                            return True
                    else:
                        # Use regular SMTP with optional STARTTLS (port 587 or 25)
                        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                            if use_tls:
                                server.starttls(context=context)
                            server.login(smtp_username, smtp_password)
                            server.sendmail(from_addr=mail_sender, to_addrs=[user_email], msg=msg.as_string())
                            return True

                except Exception as e:
                    logging.warning(f"Password reset confirmation email error: {str(e)}")
                    return False

            # Submit the email sending task to the thread pool executor
            try:
                future = email_executor.submit(
                    send_confirmation_email_worker,
                    user_email, smtp_server, smtp_port, use_tls, use_ssl,
                    smtp_username, smtp_password, mail_sender, company_name
                )
                return future.result(timeout=30)  # Increased timeout to 30 seconds for reliable email delivery
            except FutureTimeoutError:
                logging.error("Password reset confirmation email sending timeout after 30 seconds")
                return False
            except Exception as e:
                logging.error(f"Password reset confirmation email sending failed: {str(e)}")
                return False

        except ValueError as e:
            # Email settings not configured
            logging.error(f"Email configuration error: {str(e)}")
            return False
        except Exception as e:
            logging.error(f"Error in _send_password_reset_confirmation_email: {e}", exc_info=True)
            return False
    
    @staticmethod
    def _send_password_change_confirmation_email(user: User) -> bool:
        """
        Send confirmation email after successful password change by authenticated user using admin panel email settings with thread pool executor
        """
        try:
            # Get email configuration from admin panel
            email_config = get_admin_email_settings()

            smtp_server = email_config['smtp_host']
            smtp_port = email_config['smtp_port']
            use_tls = email_config['use_tls']
            use_ssl = email_config['use_ssl']
            smtp_username = email_config['username']
            smtp_password = email_config['password']
            mail_sender = email_config['sender_email']

            # Capture user email as string to avoid Flask context issues
            user_email = user.email

            def send_change_confirmation_email_worker(user_email, smtp_server, smtp_port, use_tls, use_ssl, smtp_username, smtp_password, mail_sender):
                """Worker function that runs in background thread"""
                try:
                    import smtplib
                    import ssl
                    from email.mime.text import MIMEText
                    from email.mime.multipart import MIMEMultipart
                    from datetime import datetime
                    
                    # Create multipart message with proper headers
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = '🔒 Password Changed Successfully - {company_name} Security Alert'
                    msg['From'] = f"{company_name} Security <{mail_sender}>"
                    msg['To'] = user_email
                    msg['Reply-To'] = mail_sender

                    # Essential email headers
                    msg['Date'] = time.strftime('%a, %d %b %Y %H:%M:%S %z', time.gmtime())
                    msg['Message-ID'] = f"<fleetwise-change-{int(time.time())}-{hash(user_email) % 100000}@{mail_sender.split('@')[1]}>"
                    msg['X-Mailer'] = "{company_name}"
                    msg['MIME-Version'] = "1.0"

                    # Priority headers for notifications (High Priority)
                    msg['X-Priority'] = "1 (Highest)"
                    msg['Priority'] = "urgent"
                    msg['Importance'] = "high"

                    # Sender authentication headers
                    msg['Return-Path'] = mail_sender

                    # Mark as transactional
                    msg['Precedence'] = "bulk"
                    msg['X-Content-Category'] = "Transactional"
                    msg['X-Email-Type'] = "Account-Security-Notification"
                    
                    # Get current timestamp
                    current_time = datetime.now().strftime("%B %d, %Y at %I:%M %p")
                    
                    # Create HTML content
                    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Password Changed Successfully</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #d4edda; padding: 20px; text-align: center; border-radius: 8px;">
            <h1 style="color: #155724; margin: 0;">[SUCCESS] Password Changed Successfully</h1>
        </div>
        <div style="padding: 20px;">
            <p>Hello,</p>
            
            <p><strong>Your {company_name} account password has been successfully changed.</strong></p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 4px; margin: 15px 0;">
                <p style="margin: 0;"><strong>Account Details:</strong></p>
                <p style="margin: 5px 0;">Email: {user_email}</p>
                <p style="margin: 5px 0;">🕐 Change Time: {current_time}</p>
                <p style="margin: 5px 0;">🔒 Method: Account Settings</p>
            </div>
            
            <div style="background-color: #fff3cd; padding: 15px; border-radius: 4px; margin: 15px 0; border-left: 4px solid #ffc107;">
                <p style="margin: 0;"><strong>[WARNING] Security Notice:</strong></p>
                <ul style="margin: 10px 0;">
                    <li>If you did not make this password change, your account may be compromised</li>
                    <li>Please log in immediately to review your account security</li>
                    <li>Consider enabling two-factor authentication for additional protection</li>
                    <li>Contact our support team immediately if this was unauthorized</li>
                </ul>
            </div>
            
            <div style="background-color: #d1ecf1; padding: 15px; border-radius: 4px; margin: 15px 0;">
                <p style="margin: 0;"><strong>[TIPS] Security Recommendations:</strong></p>
                <ul style="margin: 10px 0;">
                    <li>Your new password should be strong and unique</li>
                    <li>Don't reuse this password on other websites</li>
                    <li>Keep your password confidential</li>
                    <li>Log out from any shared or public devices</li>
                    <li>Monitor your account for any suspicious activity</li>
                </ul>
            </div>
            
            <p>This password change was initiated from your account settings. You can continue using {company_name} with your new password.</p>
            
            <p>If you have any questions or concerns about this password change, please contact our support team immediately.</p>
            
            <p>Best regards,<br>{company_name} Security Team</p>
        </div>
        <div style="font-size: 12px; color: #666; margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 4px;">
            <p style="margin: 0;">This is an automated security notification. Please do not reply to this email.</p>
            <p style="margin: 5px 0 0 0;">If you believe this email was sent in error, please contact our support team immediately.</p>
        </div>
    </div>
</body>
</html>
                    """
                    
                    # Create text version
                    text_content = f"""
{company_name} - Password Changed Successfully

Hello,

Your {company_name} account password has been successfully changed.

Account Details:
- Email: {user_email}
- Change Time: {current_time}
- Method: Account Settings

SECURITY NOTICE:
If you did not make this password change, your account may be compromised.
Please log in immediately to review your account security.
Consider enabling two-factor authentication for additional protection.
Contact our support team immediately if this was unauthorized.

Security Recommendations:
- Your new password should be strong and unique
- Don't reuse this password on other websites
- Keep your password confidential
- Log out from any shared or public devices
- Monitor your account for any suspicious activity

This password change was initiated from your account settings. You can continue using {company_name} with your new password.

If you have any questions or concerns about this password change, please contact our support team immediately.

Best regards,
{company_name} Security Team

This is an automated security notification. Please do not reply to this email.
If you believe this email was sent in error, please contact our support team immediately.
                    """
                    
                    # Attach parts
                    text_part = MIMEText(text_content, 'plain')
                    html_part = MIMEText(html_content, 'html')
                    msg.attach(text_part)
                    msg.attach(html_part)

                    # Send email using configured SMTP settings
                    context = ssl.create_default_context()

                    if use_ssl:
                        # Use SMTP_SSL for SSL connections (port 465)
                        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30, context=context) as server:
                            server.login(smtp_username, smtp_password)
                            result = server.send_message(msg)
                            return not bool(result)  # Empty dict means success
                    else:
                        # Use regular SMTP with optional STARTTLS (port 587 or 25)
                        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                            if use_tls:
                                server.starttls(context=context)
                            server.login(smtp_username, smtp_password)
                            result = server.send_message(msg)
                            return not bool(result)  # Empty dict means success

                except Exception as e:
                    logging.warning(f"Password change confirmation email error: {str(e)}")
                    return False

            # Submit the email sending task to the thread pool executor
            try:
                future = email_executor.submit(
                    send_change_confirmation_email_worker,
                    user_email, smtp_server, smtp_port, use_tls, use_ssl,
                    smtp_username, smtp_password, mail_sender, company_name
                )
                return future.result(timeout=30)  # Increased timeout to 30 seconds for reliable email delivery
            except FutureTimeoutError:
                logging.error("Password change confirmation email sending timeout after 30 seconds")
                return False
            except Exception as e:
                logging.error(f"Password change confirmation email sending failed: {str(e)}")
                return False

        except ValueError as e:
            # Email settings not configured
            logging.error(f"Email configuration error: {str(e)}")
            return False
        except Exception as e:
            logging.error(f"Error in _send_password_change_confirmation_email: {e}", exc_info=True)
            return False