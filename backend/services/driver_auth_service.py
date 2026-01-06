import logging
from datetime import datetime
from backend.extensions import db
from backend.models.driver import Driver
from backend.models.otp_storage import OTPStorage
from backend.models.user import User
from backend.services.password_reset_service import PasswordResetService, PasswordResetError
from flask_security.utils import hash_password, verify_password
from backend.utils.validation import validate_password_reset_data


class DriverAuthError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message = message
        self.code = code


class DriverAuthService:
    @staticmethod
    def request_driver_password_reset(email: str) -> bool:
        """
        Initiate password reset process for a driver by sending OTP to their email
        
        Args:
            email: Driver's email address
            
        Returns:
            bool: True if OTP was sent successfully
        """
        try:
            # For security reasons, always generate and attempt to send OTP even if driver doesn't exist
            # This prevents email enumeration attacks

            # Generate OTP for the email (regardless of whether driver exists)
            otp = OTPStorage.generate_otp(email, expiry_minutes=15)  # OTP expires in 15 minutes

            # Find the driver to get their information for the email, if they exist
            driver = Driver.query.filter_by(email=email).first()
            driver_name = driver.name if driver else email.split('@')[0]  # Use email prefix if name not available

            # Send OTP via email using the existing email service
            email_sent = DriverAuthService._send_otp_email(email, otp, driver_name)

            if email_sent:
                logging.info(f"OTP {otp} sent successfully to email: {email}")
            else:
                logging.error(f"Failed to send OTP to email: {email}")
                # Note: We still return True for security (don't reveal delivery status)

            return True
            
        except Exception as e:
            logging.error(f"Error in request_driver_password_reset: {e}", exc_info=True)
            raise DriverAuthError("Unable to process driver password reset request. Please try again later.", 500)

    @staticmethod
    def verify_driver_otp(otp: str) -> dict:
        """
        Verify if the provided OTP is valid
        
        Args:
            otp: OTP to verify
            
        Returns:
            dict: Contains email if OTP is valid, otherwise error details
        """
        try:
            # Find the OTP record to get the associated email
            otp_record = OTPStorage.query.filter_by(otp=otp, used=False).first()
            
            if not otp_record:
                return {'valid': False, 'error': 'Invalid or expired OTP'}
            
            # Check if OTP has expired
            if datetime.utcnow() > otp_record.expires_at:
                # Mark as used to prevent reuse
                otp_record.used = True
                db.session.commit()
                return {'valid': False, 'error': 'OTP has expired'}
            
            # OTP is valid, return the email and mark as used
            email = otp_record.email
            otp_record.used = True
            db.session.commit()
            
            return {'valid': True, 'email': email}
            
        except Exception as e:
            logging.error(f"Error in verify_driver_otp: {e}", exc_info=True)
            raise DriverAuthError("Unable to verify OTP. Please try again later.", 500)

    @staticmethod
    def reset_driver_password_with_email_only(email: str, new_password: str, confirm_password: str) -> bool:
        """
        Reset driver password after OTP verification has been completed
        For now, this implementation will validate that the user exists and reset the password
        In a real implementation, you would track OTP validation in a session or temporary token
        
        Args:
            email: Driver's email address
            new_password: New password
            confirm_password: Password confirmation
            
        Returns:
            bool: True if password was reset successfully
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
                raise DriverAuthError(f"Password validation failed: {'; '.join(error_messages)}")

            # Find the driver
            driver = Driver.query.filter_by(email=email).first()
            # If no driver found, we'll still continue (for flexibility)
            if not driver:
                logging.info(f"Driver account not found for email: {email}, continuing")

            # Find the associated user account (if exists) and update the password
            # In this system, drivers may have associated user accounts
            user = User.query.filter_by(email=email).first()
            if not user:
                # If no user account exists, we can't reset the password
                # This could happen if the driver doesn't have a login account
                logging.warning(f"No user account found for email: {email}")
                raise DriverAuthError("User account not found.", 400)

            # Check for password reuse using the existing password history mechanism
            from backend.models.password_history import PasswordHistory
            recent_passwords = PasswordHistory.get_recent_passwords(user.id, 5)
            for old_password_hash in recent_passwords:
                if verify_password(new_password, old_password_hash):
                    raise DriverAuthError("Cannot reuse any of your last 5 passwords.", 400)

            # Update password
            hashed_password = hash_password(new_password)
            user.password = hashed_password

            # Add to password history
            PasswordHistory.add_to_history(user.id, hashed_password)

            # Commit changes
            db.session.commit()

            # Send password reset confirmation email using the existing service
            try:
                PasswordResetService._send_password_reset_confirmation_email(user)
            except Exception as email_error:
                logging.error(f"Failed to send password reset confirmation email: {email_error}")

            logging.info(f"Driver password reset successful for email: {email}")
            return True

        except DriverAuthError:
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in reset_driver_password_with_email_only: {e}", exc_info=True)
            raise DriverAuthError("Unable to reset driver password. Please try again later.", 500)

    @staticmethod
    def _send_otp_email(email: str, otp: str, driver_name: str) -> bool:
        """
        Send OTP to driver's email using admin panel configuration
        
        Args:
            email: Driver's email address
            otp: OTP to send
            driver_name: Driver's name for the email
            
        Returns:
            bool: True if email was sent successfully
        """
        try:
            from flask import current_app
            from backend.models.settings import UserSettings
            from cryptography.fernet import Fernet
            import smtplib
            import ssl
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            import time

            # Get email configuration from admin panel (same as PasswordResetService)
            settings = UserSettings.query.first()

            if not settings or not settings.preferences:
                logging.error("Email settings not found in database")
                return False

            prefs = dict(settings.preferences)
            email_settings = prefs.get('email_settings', {})

            if not email_settings or not email_settings.get('smtp_host'):
                logging.error("Email SMTP settings not configured in database")
                return False

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
                            return False
                except Exception as e:
                    logging.error(f"Error processing email password: {e}")
                    return False

            # Validate required fields
            if not email_settings.get('username'):
                logging.error("Email username not configured")
                return False

            if not password:
                logging.error("Email password not configured")
                return False

            smtp_server = email_settings['smtp_host']
            smtp_port = int(email_settings.get('smtp_port', 587))
            use_tls = email_settings.get('use_tls', True)
            use_ssl = email_settings.get('use_ssl', False)
            smtp_username = email_settings['username']
            mail_sender = email_settings.get('sender_email', 'noreply@fleetwise.com')
            
            # Create multipart message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'Password Reset OTP - FleetWise Driver Account'
            msg['From'] = f"FleetWise Support <{mail_sender}>"
            msg['To'] = email
            
            # Create email content
            text_content = f"""
Hello {driver_name},

You have requested to reset your FleetWise driver account password. Please use the following One-Time Password (OTP) to complete the reset process:

Your OTP: {otp}

This OTP will expire in 10 minutes. If you did not request a password reset, please ignore this email.

For security reasons, please do not share this OTP with anyone.

Best regards,
FleetWise Team
            """
            
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Password Reset OTP</title>
</head>
<body>
    <div style="max-width: 600px; margin: 0 auto; padding: 20px; font-family: Arial, sans-serif;">
        <h2>Password Reset OTP - FleetWise Driver Account</h2>
        <p>Hello {driver_name},</p>
        <p>You have requested to reset your FleetWise driver account password. Please use the following One-Time Password (OTP) to complete the reset process:</p>
        <div style="text-align: center; margin: 20px 0;">
            <h1 style="color: #dc3545; font-size: 32px;">{otp}</h1>
        </div>
        <p><strong>This OTP will expire in 10 minutes.</strong> If you did not request a password reset, please ignore this email.</p>
        <p>For security reasons, please do not share this OTP with anyone.</p>
        <p>Best regards,<br>FleetWise Team</p>
    </div>
</body>
</html>
            """
            
            # Attach content
            text_part = MIMEText(text_content, 'plain')
            html_part = MIMEText(html_content, 'html')
            msg.attach(text_part)
            msg.attach(html_part)
            
            # Send email using configured SMTP settings
            context = ssl.create_default_context()

            if use_ssl:
                # Use SMTP_SSL for SSL connections (port 465)
                with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30, context=context) as server:
                    server.login(smtp_username, password)
                    server.send_message(msg)
                    return True
            else:
                # Use regular SMTP with optional STARTTLS (port 587 or 25)
                with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                    if use_tls:
                        server.starttls(context=context)
                    server.login(smtp_username, password)
                    server.send_message(msg)
                    return True
            
        except Exception as e:
            logging.error(f"Error sending OTP email to {email}: {e}", exc_info=True)
            return False

    @staticmethod
    def cleanup_expired_otps() -> int:
        """
        Clean up expired OTPs from database
        
        Returns:
            int: Number of expired OTPs cleaned up
        """
        try:
            count = OTPStorage.cleanup_expired_otps()
            logging.info(f"Cleaned up {count} expired driver OTPs")
            return count
        except Exception as e:
            logging.error(f"Error cleaning up expired OTPs: {e}", exc_info=True)
            return 0