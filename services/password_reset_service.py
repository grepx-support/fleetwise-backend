import logging
import queue
import threading
from datetime import datetime
from typing import Optional, Tuple
from flask import current_app, render_template_string
from flask_mail import Message
from flask_security.utils import hash_password, verify_password

from backend.extensions import db, mail
from backend.models.user import User
from backend.models.password_reset_token import PasswordResetToken
from backend.utils.validation import (
    validate_password_change_data,
    validate_password_reset_request_data,
    validate_password_reset_data,
    validate_password_strength
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
            frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:3000')
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
            
            # Update password
            user.password = hash_password(new_password)
            
            # Commit changes
            db.session.commit()
            
            # Send password reset confirmation email
            PasswordResetService._send_password_reset_confirmation_email(user)
            
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
            
            # Update password
            user.password = hash_password(new_password)
            
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
    def _send_reset_email(user: User, token: str) -> None:
        """
        Send password reset email to user
        
        Args:
            user: User object
            token: Raw reset token
            
        Raises:
            PasswordResetError: If email sending fails
        """
        try:
            frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:3000')
            reset_link = f"{frontend_url}/reset-password/{token}"
            
            # Email template
            email_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Password Reset Request</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #f8f9fa; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .button { 
            display: inline-block; 
            padding: 12px 24px; 
            background-color: #007bff; 
            color: white; 
            text-decoration: none; 
            border-radius: 4px; 
            margin: 20px 0; 
        }
        .footer { font-size: 12px; color: #666; margin-top: 20px; }
        .warning { background-color: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>FleetWise - Password Reset</h1>
        </div>
        <div class="content">
            <p>Hello,</p>
            
            <p>We received a request to reset the password for your FleetWise account ({{ email }}).</p>
            
            <p>Click the button below to reset your password:</p>
            
            <p><a href="{{ reset_link }}" class="button">Reset Password</a></p>
            
            <p>Or copy and paste this link into your browser:</p>
            <p><a href="{{ reset_link }}">{{ reset_link }}</a></p>
            
            <div class="warning">
                <strong>Important:</strong>
                <ul>
                    <li>This link will expire in {{ expiry_hours }} hour(s)</li>
                    <li>This link can only be used once</li>
                    <li>If you didn't request this password reset, please ignore this email</li>
                </ul>
            </div>
            
            <p>If you have any questions, please contact our support team.</p>
            
            <p>Best regards,<br>FleetWise Team</p>
        </div>
        <div class="footer">
            <p>This is an automated message. Please do not reply to this email.</p>
        </div>
    </div>
</body>
</html>
            """
            
            # Render email template
            html_content = render_template_string(
                email_template,
                email=user.email,
                reset_link=reset_link,
                expiry_hours=current_app.config.get('PASSWORD_RESET_TOKEN_EXPIRY_HOURS', 1)
            )
            
            # Create and send message
            msg = Message(
                subject='FleetWise - Password Reset Request',
                recipients=[user.email],
                html=html_content,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER')
            )
            
            mail.send(msg)
            
        except Exception as e:
            logging.error(f"Flask-Mail failed: {e}")
            # Try direct SMTP as fallback
            try:
                PasswordResetService._send_with_direct_smtp(user, reset_link)
                logging.info(f"Email sent successfully via direct SMTP to {user.email}")
            except Exception as smtp_error:
                logging.error(f"Direct SMTP also failed: {smtp_error}")
                raise PasswordResetError("Unable to send reset email. Please try again later.", 500)
    
    @staticmethod
    def _send_reset_email_threaded(user: User, reset_link: str) -> bool:
        """
        Send password reset email using only Zoho credentials with thread pool executor
        """
        import os
        
        # Use only Zoho credentials directly from environment (not Flask config)
        smtp_server = 'smtp.zoho.com'
        smtp_port = 587
        smtp_username = os.getenv('ZOHO_USER')
        smtp_password = os.getenv('ZOHO_PASSWORD')
        mail_sender = smtp_username  # Use Zoho email as sender
        
        # Validate that required credentials are provided
        if not smtp_username or not smtp_password:
            logging.error("Email service credentials not configured. Please set ZOHO_USER and ZOHO_PASSWORD environment variables.")
            return False
        
        # Capture user email as string to avoid Flask context issues
        user_email = user.email
        
        # Debug: Log Zoho config (without password)
        logging.info(f"Using Zoho config - Server: {smtp_server}, Port: {smtp_port}, Sender: {mail_sender}")
        
        def send_zoho_email_worker(user_email, reset_link, smtp_server, smtp_port, smtp_username, smtp_password, mail_sender):
            """Worker function that runs in background thread using only Zoho"""
            try:
                import smtplib
                import ssl
                import time
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                
                # Create multipart message with Zoho-specific headers
                msg = MIMEMultipart('alternative')
                msg['Subject'] = 'FleetWise - Password Reset Request'
                msg['From'] = f"FleetWise Support <{mail_sender}>"
                msg['To'] = user_email
                msg['Reply-To'] = mail_sender
                
                # Essential anti-spam headers for Zoho
                msg['Date'] = time.strftime('%a, %d %b %Y %H:%M:%S %z', time.gmtime())
                msg['Message-ID'] = f"<fleetwise-reset-{int(time.time())}-{hash(user_email) % 100000}@grepx.co.in>"
                msg['X-Mailer'] = "FleetWise Password Reset System v2.0"
                msg['X-Priority'] = "3 (Normal)"
                msg['Importance'] = "Normal"
                msg['MIME-Version'] = "1.0"
                
                # Sender authentication headers for Zoho
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
                msg['X-FleetWise-Type'] = "Password-Reset-Request"
                msg['X-Content-Category'] = "Transactional"
                
                # Create enhanced HTML content with GREPX branding
                html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset Request - FleetWise</title>
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
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">Secure password reset for your FleetWise account</p>
        </div>
        
        <div class="content">
            <p style="font-size: 16px; margin-bottom: 20px;">Hello,</p>
            
            <p style="font-size: 16px;">We received a request to reset the password for your <span class="brand">FleetWise</span> account: <strong>{user_email}</strong></p>
            
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
                <p style="font-size: 16px; margin: 0;">Thank you for using <span class="brand">FleetWise</span>.</p>
                <p style="font-size: 16px; margin: 15px 0 0 0;"><strong>Best regards,<br>FleetWise Security Team<br><span class="brand">GREPX Technologies</span></strong></p>
            </div>
        </div>
        
        <div class="footer">
            <p style="margin: 0 0 5px 0;">This is an automated security notification from FleetWise.</p>
            <p style="margin: 0 0 5px 0;">(c) 2024 GREPX Technologies. All rights reserved.</p>
            <p style="margin: 0; font-style: italic;">Please do not reply to this email.</p>
        </div>
    </div>
</body>
</html>
                """
                
                # Create professional text version
                text_content = f"""
FleetWise - Password Reset Request

Hello,

We received a request to reset the password for your FleetWise account: {user_email}

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

Thank you for using FleetWise.

Best regards,
FleetWise Security Team
GREPX Technologies

---
This is an automated security notification from FleetWise.
(c) 2024 GREPX Technologies. All rights reserved.
Please do not reply to this email.
                """
                
                # Attach content parts
                text_part = MIMEText(text_content, 'plain', 'utf-8')
                html_part = MIMEText(html_content, 'html', 'utf-8')
                msg.attach(text_part)
                msg.attach(html_part)
                
                # Send email using only Zoho SMTP
                context = ssl.create_default_context()
                
                with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                    server.starttls(context=context)
                    server.login(smtp_username, smtp_password)
                    
                    # Send with Zoho sender address
                    result = server.send_message(msg)
                    
                    if result:
                        # Some recipients failed
                        return False
                    else:
                        # All recipients succeeded
                        return True
                        
            except Exception as e:
                # Log the error and return False
                logging.error(f"Zoho password reset email error: {str(e)}")
                return False
        
        # Submit the email sending task to the thread pool executor
        try:
            future = email_executor.submit(send_zoho_email_worker, user_email, reset_link, smtp_server, smtp_port, smtp_username, smtp_password, mail_sender)
            return future.result(timeout=8)  # Reasonable timeout for API response
        except FutureTimeoutError:
            logging.warning("Email sending timeout")
            return False
        except Exception as e:
            logging.error(f"Email sending failed: {str(e)}")
            return False
    
    @staticmethod
    def _send_password_reset_confirmation_email(user: User) -> None:
        """
        Send password reset confirmation email to user
        
        Args:
            user: User object
        """
        try:
            frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:3000')
            reset_link = f"{frontend_url}/login"
            
            # Email template
            email_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Password Reset Confirmation</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #f8f9fa; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .button { 
            display: inline-block; 
            padding: 12px 24px; 
            background-color: #007bff; 
            color: white; 
            text-decoration: none; 
            border-radius: 4px; 
            margin: 20px 0; 
        }
        .footer { font-size: 12px; color: #666; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>FleetWise - Password Reset Confirmation</h1>
        </div>
        <div class="content">
            <p>Hello,</p>
            
            <p>Your password has been successfully reset.</p>
            
            <p>Click the button below to log in:</p>
            
            <p><a href="{{ reset_link }}" class="button">Log In</a></p>
            
            <p>Or copy and paste this link into your browser:</p>
            <p><a href="{{ reset_link }}">{{ reset_link }}</a></p>
            
            <p>If you have any questions, please contact our support team.</p>
            
            <p>Best regards,<br>FleetWise Team</p>
        </div>
        <div class="footer">
            <p>This is an automated message. Please do not reply to this email.</p>
        </div>
    </div>
</body>
</html>
            """
            
            # Render email template
            html_content = render_template_string(
                email_template,
                reset_link=reset_link
            )
            
            # Create and send message
            msg = Message(
                subject='FleetWise - Password Reset Confirmation',
                recipients=[user.email],
                html=html_content,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER')
            )
            
            mail.send(msg)
            
        except Exception as e:
            logging.error(f"Flask-Mail failed: {e}")
            # Try direct SMTP as fallback
            try:
                PasswordResetService._send_with_direct_smtp(user, reset_link)
                logging.info(f"Email sent successfully via direct SMTP to {user.email}")
            except Exception as smtp_error:
                logging.error(f"Direct SMTP also failed: {smtp_error}")
                raise PasswordResetError("Unable to send reset confirmation email. Please try again later.", 500)
    
    @staticmethod
    def _send_password_change_confirmation_email(user: User) -> None:
        """
        Send password change confirmation email to user
        
        Args:
            user: User object
        """
        try:
            frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:3000')
            reset_link = f"{frontend_url}/login"
            
            # Email template
            email_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Password Change Confirmation</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #f8f9fa; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .button { 
            display: inline-block; 
            padding: 12px 24px; 
            background-color: #007bff; 
            color: white; 
            text-decoration: none; 
            border-radius: 4px; 
            margin: 20px 0; 
        }
        .footer { font-size: 12px; color: #666; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>FleetWise - Password Change Confirmation</h1>
        </div>
        <div class="content">
            <p>Hello,</p>
            
            <p>Your password has been successfully changed.</p>
            
            <p>Click the button below to log in:</p>
            
            <p><a href="{{ reset_link }}" class="button">Log In</a></p>
            
            <p>Or copy and paste this link into your browser:</p>
            <p><a href="{{ reset_link }}">{{ reset_link }}</a></p>
            
            <p>If you have any questions, please contact our support team.</p>
            
            <p>Best regards,<br>FleetWise Team</p>
        </div>
        <div class="footer">
            <p>This is an automated message. Please do not reply to this email.</p>
        </div>
    </div>
</body>
</html>
            """
            
            # Render email template
            html_content = render_template_string(
                email_template,
                reset_link=reset_link
            )
            
            # Create and send message
            msg = Message(
                subject='FleetWise - Password Change Confirmation',
                recipients=[user.email],
                html=html_content,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER')
            )
            
            mail.send(msg)
            
        except Exception as e:
            logging.error(f"Flask-Mail failed: {e}")
            # Try direct SMTP as fallback
            try:
                PasswordResetService._send_with_direct_smtp(user, reset_link)
                logging.info(f"Email sent successfully via direct SMTP to {user.email}")
            except Exception as smtp_error:
                logging.error(f"Direct SMTP also failed: {smtp_error}")
                raise PasswordResetError("Unable to send change confirmation email. Please try again later.", 500)
    
    @staticmethod
    def _send_with_direct_smtp(user: User, reset_link: str) -> None:
        """
        Send password reset email using only Zoho credentials with direct SMTP
        
        Args:
            user: User object
            reset_link: Reset link to be included in email
            
        Raises:
            PasswordResetError: If email sending fails
        """
        import os
        
        # Use only Zoho credentials directly from environment (not Flask config)
        smtp_server = 'smtp.zoho.com'
        smtp_port = 587
        smtp_username = os.getenv('ZOHO_USER')
        smtp_password = os.getenv('ZOHO_PASSWORD')
        mail_sender = smtp_username  # Use Zoho email as sender
        
        # Validate that required credentials are provided
        if not smtp_username or not smtp_password:
            logging.error("Email service credentials not configured")
            return False
        
    @staticmethod
    def _send_password_reset_confirmation_email(user: User) -> bool:
        """
        Send confirmation email after successful password reset using Zoho credentials with thread pool executor
        """
        try:
            import os
            
            # Use only Zoho credentials directly from environment
            smtp_server = 'smtp.zoho.com'
            smtp_port = 587
            smtp_username = os.getenv('ZOHO_USER')
            smtp_password = os.getenv('ZOHO_PASSWORD')
            mail_sender = smtp_username  # Use Zoho email as sender
            
            # Validate that required credentials are provided
            if not smtp_username or not smtp_password:
                logging.error("Email service credentials not configured")
                return False
            
            # Capture user email as string to avoid Flask context issues
            user_email = user.email
            
            def send_zoho_confirmation_email_worker(user_email, smtp_server, smtp_port, smtp_username, smtp_password, mail_sender):
                """Worker function that runs in background thread using only Zoho"""
                try:
                    import smtplib
                    import ssl
                    import time
                    from email.mime.text import MIMEText
                    from email.mime.multipart import MIMEMultipart
                    from datetime import datetime
                    
                    # Create multipart message with Zoho-specific headers
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = 'Password Updated Successfully - FleetWise Account Security'
                    msg['From'] = f"FleetWise Support <{mail_sender}>"
                    msg['To'] = user_email
                    msg['Reply-To'] = mail_sender
                    
                    # Essential anti-spam headers for Zoho
                    msg['Date'] = time.strftime('%a, %d %b %Y %H:%M:%S %z', time.gmtime())
                    msg['Message-ID'] = f"<fleetwise-{int(time.time())}-{hash(user_email) % 100000}@grepx.co.in>"
                    msg['X-Mailer'] = "FleetWise Security System v2.0"
                    msg['X-Priority'] = "3 (Normal)"
                    msg['Importance'] = "Normal"
                    msg['MIME-Version'] = "1.0"
                    
                    # Sender authentication headers for Zoho
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
                    msg['X-FleetWise-Type'] = "Password-Reset-Confirmation"
                    msg['X-Content-Category'] = "Transactional"
                    
                    # Get current timestamp
                    current_time = datetime.now().strftime("%B %d, %Y at %I:%M %p")
                    
                    # Professional text content
                    text_content = f"""
Password Reset Successful - FleetWise Account Security

Dear Valued Customer,

This email confirms that your FleetWise account password has been successfully updated on {current_time}.

ACCOUNT SECURITY CONFIRMATION:
Account Email: {user_email}
Update Timestamp: {current_time}
Security Status: Password Successfully Updated
Authentication: Verified Secure Connection

SECURITY NOTIFICATION:
Your FleetWise account is now protected with your new password. If you did not initiate this password reset, please contact our security team immediately at {mail_sender}.

ACCOUNT ACCESS:
You can now log in to FleetWise using your new password credentials. We recommend enabling two-factor authentication for enhanced account security.

SECURITY RECOMMENDATIONS:
- Use a strong, unique password for your FleetWise account
- Never share your login credentials with anyone
- Keep your password confidential and secure
- Monitor your account for any suspicious activity
- Enable two-factor authentication when available

SUPPORT ASSISTANCE:
If you have any questions or need assistance, our support team is available 24/7.
Contact: {mail_sender}
Website: https://fleetwise.grepx.co.in

Thank you for using FleetWise.

Best regards,
FleetWise Security Team
GREPX Technologies

---
This is an automated security notification from FleetWise.
You received this email because a password reset was completed on your account.
(c) 2024 GREPX Technologies. All rights reserved.

If you believe this email was sent in error, please contact our support team immediately.
                    """
                    
                    # Enhanced HTML content with GREPX branding
                    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset Successful - FleetWise</title>
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
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">Your FleetWise account is now secure</p>
        </div>
        
        <div class="content">
            <p style="font-size: 16px; margin-bottom: 20px;">Dear Valued Customer,</p>
            
            <p style="font-size: 16px;">This email confirms that your <span class="brand">FleetWise</span> account password has been <span class="highlight">successfully updated</span> on <strong>{current_time}</strong>.</p>
            
            <div class="info-section">
                <h3 style="margin-top: 0; color: #2c5aa0;">[INFO] Account Security Confirmation</h3>
                <p style="margin: 8px 0;"><strong>Account Email:</strong> {user_email}</p>
                <p style="margin: 8px 0;"><strong>Update Time:</strong> {current_time}</p>
                <p style="margin: 8px 0;"><strong>Security Status:</strong> <span class="status-badge">Password Updated</span></p>
                <p style="margin: 8px 0;"><strong>Authentication:</strong> Verified Secure Connection</p>
            </div>
            
            <div class="security-section">
                <h3 style="margin-top: 0; color: #155724;">[CONFIRMED] Security Confirmation</h3>
                <p style="margin: 8px 0; color: #155724;">Your <span class="brand">FleetWise</span> account is now protected with your new password credentials.</p>
                <p style="margin: 8px 0; color: #155724;"><strong>Important:</strong> If you did not initiate this password reset, please contact our security team immediately.</p>
            </div>
            
            <h3 style="color: #2c5aa0; font-size: 18px; margin: 25px 0 15px 0;">[ACCESS] Account Access</h3>
            <p style="font-size: 16px;">You can now log in to <span class="brand">FleetWise</span> using your new password credentials. We recommend enabling two-factor authentication for enhanced account security.</p>
            
            <h3 style="color: #2c5aa0; font-size: 18px; margin: 25px 0 15px 0;">[SUPPORT] Support Assistance</h3>
            <p style="font-size: 16px;">If you have any questions or need assistance, our support team is available 24/7.</p>
            <p style="font-size: 16px;"><strong>Contact:</strong> <a href="mailto:{mail_sender}" style="color: #2c5aa0; text-decoration: none;">{mail_sender}</a></p>
            
            <div style="margin: 30px 0; text-align: center; padding: 20px; background: #f8f9fa; border-radius: 8px;">
                <p style="font-size: 16px; margin: 0;">Thank you for using <span class="brand">FleetWise</span>.</p>
                <p style="font-size: 16px; margin: 15px 0 0 0;"><strong>Best regards,<br>FleetWise Security Team<br><span class="brand">GREPX Technologies</span></strong></p>
            </div>
        </div>
        
        <div class="footer">
            <p style="margin: 0 0 5px 0;">This is an automated security notification from FleetWise.</p>
            <p style="margin: 0 0 5px 0;">(c) 2024 GREPX Technologies. All rights reserved.</p>
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
                    
                    # Send email using only Zoho SMTP
                    context = ssl.create_default_context()
                    
                    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                        server.starttls(context=context)
                        server.login(smtp_username, smtp_password)
                        
                        # Send with Zoho sender address
                        server.sendmail(
                            from_addr=mail_sender,
                            to_addrs=[user_email],
                            msg=msg.as_string()
                        )
                        
                        server.quit()
                        
                        return True
                        
                except Exception as e:
                    logging.warning(f"Zoho password reset confirmation email error: {str(e)}")
                    return False
            
            # Submit the email sending task to the thread pool executor
            try:
                future = email_executor.submit(send_zoho_confirmation_email_worker, user_email, smtp_server, smtp_port, smtp_username, smtp_password, mail_sender)
                return future.result(timeout=8)  # Reasonable timeout for API response
            except FutureTimeoutError:
                logging.warning("Email sending timeout")
                return False
            except Exception as e:
                logging.warning(f"Email sending failed: {str(e)}")
                return False
                
        except Exception as e:
            logging.error(f"Error in _send_password_reset_confirmation_email: {e}", exc_info=True)
            return False
    
    @staticmethod
    def _send_password_change_confirmation_email(user: User) -> bool:
        """
        Send confirmation email after successful password change by authenticated user with thread pool executor
        """
        try:
            # Capture config values from Flask context before threading
            smtp_server = current_app.config.get('MAIL_SERVER')
            smtp_port = current_app.config.get('MAIL_PORT')
            smtp_username = current_app.config.get('MAIL_USERNAME')
            smtp_password = current_app.config.get('MAIL_PASSWORD')
            mail_sender = current_app.config.get('MAIL_DEFAULT_SENDER')
            
            # Capture user email as string to avoid Flask context issues
            user_email = user.email
            
            def send_change_confirmation_email_worker(user_email, smtp_server, smtp_port, smtp_username, smtp_password, mail_sender):
                """Worker function that runs in background thread"""
                try:
                    import smtplib
                    import ssl
                    from email.mime.text import MIMEText
                    from email.mime.multipart import MIMEMultipart
                    from datetime import datetime
                    
                    # Create multipart message
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = 'FleetWise - Password Changed Successfully'
                    msg['From'] = mail_sender
                    msg['To'] = user_email
                    
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
            
            <p><strong>Your FleetWise account password has been successfully changed.</strong></p>
            
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
            
            <p>This password change was initiated from your account settings. You can continue using FleetWise with your new password.</p>
            
            <p>If you have any questions or concerns about this password change, please contact our support team immediately.</p>
            
            <p>Best regards,<br>FleetWise Security Team</p>
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
FleetWise - Password Changed Successfully

Hello,

Your FleetWise account password has been successfully changed.

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

This password change was initiated from your account settings. You can continue using FleetWise with your new password.

If you have any questions or concerns about this password change, please contact our support team immediately.

Best regards,
FleetWise Security Team

This is an automated security notification. Please do not reply to this email.
If you believe this email was sent in error, please contact our support team immediately.
                    """
                    
                    # Attach parts
                    text_part = MIMEText(text_content, 'plain')
                    html_part = MIMEText(html_content, 'html')
                    msg.attach(text_part)
                    msg.attach(html_part)
                    
                    # Send email with SSL context
                    context = ssl.create_default_context()
                    
                    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                        server.starttls(context=context)
                        server.login(smtp_username, smtp_password)
                        result = server.send_message(msg)
                        
                        if result:
                            return False
                        else:
                            return True
                            
                except Exception as e:
                    logging.warning(f"Password change confirmation email error: {str(e)}")
                    return False
            
            # Submit the email sending task to the thread pool executor
            try:
                future = email_executor.submit(send_change_confirmation_email_worker, user_email, smtp_server, smtp_port, smtp_username, smtp_password, mail_sender)
                return future.result(timeout=8)  # Reasonable timeout for API response
            except FutureTimeoutError:
                logging.warning("Email sending timeout")
                return False
            except Exception as e:
                logging.warning(f"Email sending failed: {str(e)}")
                return False
                
        except Exception as e:
            logging.error(f"Error in _send_password_change_confirmation_email: {e}", exc_info=True)
            return False