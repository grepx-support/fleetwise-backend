import os
import logging
import socket
from backend.models.settings import UserSettings
from backend.models.system_settings import SystemSettings
from flask import Blueprint, request, jsonify
from flask_security import roles_accepted, current_user, auth_required
from werkzeug.utils import secure_filename
from PIL import Image
from io import BytesIO
import os

from backend.models.photo_config import PhotoConfig
from backend.schemas.user_settings_schema import UserSettingsSchema
from backend.services.user_settings_service import (
    get_user_settings,
    create_or_update_user_settings,
    delete_user_settings,
)
from backend.extensions import db
from sqlalchemy.orm.attributes import flag_modified
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet
import os

settings_bp = Blueprint('settings', __name__)

# Get the absolute path to the backend/static/uploads directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, '..', 'static', 'uploads')

# ---------------- UPDATE PHOTO CONFIG ----------------
@settings_bp.route('/settings/photo_config', methods=['POST'])
@auth_required()
def update_photo_config():
    """
    Update Photo Configuration in UserSettings.preferences
    """
    data = request.get_json()
    stage = data.get('stage')
    max_photos = data.get('max_photos')
    max_size_mb = data.get('max_size_mb')
    allowed_formats = data.get('allowed_formats')

    if not stage:
        return jsonify({'error': 'Stage is required'}), 400

    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    if not settings:
        settings = UserSettings(user_id=current_user.id, preferences={})

    import copy
    prefs = dict(settings.preferences) if settings.preferences else {}
    # photo_config will now be a list of dicts, one per stage
    photo_configs = copy.deepcopy(prefs.get('photo_config', []))
    if not isinstance(photo_configs, list):
        # migrate old single dict to list
        photo_configs = [photo_configs] if photo_configs else []
    # Check if stage exists
    found = False
    for config in photo_configs:
        if config.get('stage') == stage:
            if max_photos is not None:
                config['max_photos'] = int(max_photos)
            if max_size_mb is not None:
                config['max_size_mb'] = float(max_size_mb)
            if allowed_formats is not None:
                config['allowed_formats'] = allowed_formats
            found = True
            updated_config = config
            break
    if not found:
        # Append new config for this stage
        new_config = {
            'stage': stage,
            'max_photos': int(max_photos) if max_photos is not None else 1,
            'max_size_mb': float(max_size_mb) if max_size_mb is not None else 2.0,
            'allowed_formats': allowed_formats if allowed_formats is not None else 'jpg,png',
        }
        photo_configs.append(new_config)
        updated_config = new_config
    prefs['photo_config'] = photo_configs
    settings.preferences = prefs
    try:
        db.session.add(settings)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update photo config: {str(e)}'}), 500

    return jsonify({'message': f'PhotoConfig updated for stage {stage}', 'config': updated_config}), 200

# ---------------- GET PHOTO CONFIGS ----------------
@settings_bp.route('/settings/photo_config', methods=['GET'])
@auth_required()
def get_photo_config():
    """
    Get Photo Configuration from UserSettings.preferences
    """
    stage = request.args.get('stage')
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    prefs = dict(settings.preferences) if settings and settings.preferences else {}
    photo_configs = prefs.get('photo_config', [])
    if not isinstance(photo_configs, list):
        photo_configs = [photo_configs] if photo_configs else []
    if stage:
        for config in photo_configs:
            if config.get('stage') == stage:
                return jsonify({'config': config}), 200
        return jsonify({'config': None}), 200
    else:
        return jsonify({'configs': photo_configs}), 200

# --- USER SETTINGS: GET ---
@settings_bp.route('/settings/user', methods=['GET'])
@auth_required()
@roles_accepted('admin')
def get_current_user_settings():
    settings = get_user_settings(current_user.id)
    if not settings:
        return jsonify({'settings': None}), 200
    schema = UserSettingsSchema()
    return jsonify({'settings': schema.dump(settings)}), 200

# --- USER SETTINGS: CREATE/UPDATE ---
@settings_bp.route('/settings/user', methods=['POST', 'PUT'])
@auth_required()
def set_current_user_settings():
    data = request.get_json()
    preferences = data.get('preferences')
    if preferences is None:
        return jsonify({'error': 'Preferences required'}), 400

    # Always nest general_settings, billing_settings, photo_config under preferences
    def normalize_prefs(prefs):
        import copy
        norm = {}
        # Always flatten nested preferences
        for section in ['general_settings', 'billing_settings', 'photo_config']:
            if section in prefs:
                norm[section] = copy.deepcopy(prefs[section])
        # If already nested, merge in
        if 'preferences' in prefs and isinstance(prefs['preferences'], dict):
            for k, v in prefs['preferences'].items():
                norm[k] = copy.deepcopy(v)
        return norm

    normalized = normalize_prefs(preferences)
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    if not settings:
        settings = create_or_update_user_settings(current_user.id, normalized)
    else:
        # Always overwrite main sections with new values
        import copy
        prefs = copy.deepcopy(settings.preferences) if settings.preferences else {}
        for section in ['billing_settings', 'general_settings', 'photo_config']:
            if section in normalized:
                prefs[section] = normalized[section]
        try:
            settings.preferences = prefs
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e
    schema = UserSettingsSchema()
    return jsonify({'settings': schema.dump(settings)}), 200

# --- USER SETTINGS: DELETE ---
@settings_bp.route('/settings/user', methods=['DELETE'])
@auth_required()
@roles_accepted('admin')
def delete_current_user_settings():
    success = delete_user_settings(current_user.id)
    if success:
        return jsonify({'message': 'User settings deleted'}), 200
    else:
        return jsonify({'error': 'Settings not found'}), 404

# Note: upload_logo endpoint removed - use upload_file instead for better security and validation

# ---------------- UPLOAD FILE ----------------
@settings_bp.route('/settings/upload_file', methods=['POST'])
@auth_required()
def upload_file():
    import logging
    
    # Enhanced logging for debugging
    logging.info(f"Upload file request received. Content-Type: {request.content_type}")
    logging.info(f"Request files keys: {list(request.files.keys())}")
    logging.info(f"Request form data: {dict(request.form)}")
    
    # Accept either 'logo' or 'qr' as the field name
    file = request.files.get('logo') or request.files.get('qr')
    if not file or file.filename == '':
        logging.error(f"No file uploaded. Files available: {list(request.files.keys())}")
        return jsonify({'error': 'No file uploaded'}), 400

    # Validate extension
    allowed_extensions = {'jpg', 'jpeg', 'png'}
    ext = file.filename.rsplit('.', 1)[-1].lower()
    logging.info(f"File: {file.filename}, Extension: {ext}")
    if ext not in allowed_extensions:
        logging.error(f"Invalid file format: {ext}. Allowed: {allowed_extensions}")
        return jsonify({'error': f'Format not allowed. Allowed: {",".join(allowed_extensions)}'}), 400

    # Compress image (JPEG, quality 85)
    try:
        logging.info("Starting image compression...")
        img = Image.open(file)
        
        # Convert RGBA (PNG with transparency) to RGB for JPEG compatibility
        if img.mode in ('RGBA', 'LA', 'P'):
            logging.info(f"Converting image from {img.mode} to RGB for JPEG compatibility")
            # Create a white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        img_io = BytesIO()
        img.save(img_io, format='JPEG', optimize=True, quality=85)
        img_io.seek(0)
        # Optional: Check size limit (e.g., 2MB)
        size_mb = len(img_io.getbuffer()) / (1024 * 1024)
        logging.info(f"Compressed image size: {size_mb:.2f} MB")
        if size_mb > 2:
            logging.error(f"File too large after compression: {size_mb:.2f} MB")
            return jsonify({'error': 'File exceeds max size of 2 MB after compression'}), 400
    except Exception as e:
        logging.error(f"Image processing failed: {str(e)}", exc_info=True)
        return jsonify({'error': f'Image processing failed: {str(e)}'}), 500

    # Save file in static/uploads
    filename = secure_filename(file.filename.rsplit('.', 1)[0] + '_compressed.jpg')
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filepath = os.path.join(UPLOAD_DIR, filename)
    logging.info(f"Saving file to: {filepath}")

    try:
        with open(filepath, 'wb') as f:
            f.write(img_io.getbuffer())
        logging.info("File saved successfully")
    except Exception as e:
        logging.error(f"File save failed: {str(e)}", exc_info=True)
        return jsonify({'error': f'File save failed: {str(e)}'}), 500


    # Return the correct URL for frontend preview
    if 'logo' in request.files:
        logging.info(f"Returning logo_url: /static/uploads/{filename}")
        return jsonify({'logo_url': f'/static/uploads/{filename}'}), 200
    else:
        logging.info(f"Returning qr_url: /static/uploads/{filename}")
        return jsonify({'qr_url': f'/static/uploads/{filename}'}), 200

# ---------------- DELETE FILE ----------------
@settings_bp.route('/settings/delete_file', methods=['POST'])
@auth_required()
def delete_file():
    data = request.get_json()
    filename = data.get('filename')
    field = data.get('field')  # 'company_logo' or 'billing_qr_code_image'
    if not filename or not field:
        return jsonify({'error': 'Filename and field required'}), 400

    # Delete file from disk - use consistent UPLOAD_DIR path
    filepath = os.path.join(UPLOAD_DIR, os.path.basename(filename))
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
        else:
            # Don't return error here - continue to clean up database reference
            pass
    except Exception as e:
        return jsonify({'error': f'Failed to delete file: {str(e)}'}), 500

    # Remove URL from user settings (handle nested preferences and photo_config)
    import copy
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    if settings and settings.preferences:
        prefs = copy.deepcopy(settings.preferences)
        updated = False
        # Top-level billing_settings/general_settings/photo_config
        for section in ['billing_settings', 'general_settings', 'photo_config']:
            if section in prefs and field in prefs[section]:
                prefs[section][field] = ""
                updated = True
        # Nested under preferences
        if 'preferences' in prefs and isinstance(prefs['preferences'], dict):
            nested = prefs['preferences']
            for section in ['billing_settings', 'general_settings', 'photo_config']:
                if section in nested and field in nested[section]:
                    nested[section][field] = ""
                    updated = True
        if updated:
            settings.preferences = prefs  # Explicitly reassign the modified object
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return jsonify({'error': f'Failed to update settings: {str(e)}'}), 500

    return jsonify({'message': 'File and reference deleted'}), 200

def validate_email_settings(settings):
    """Validate email settings before saving."""
    errors = []
    # Validate SMTP host
    if not settings.get('smtp_host', '').strip():
        errors.append('SMTP host is required')
    # Validate port
    try:
        port = int(settings.get('smtp_port', 587))
        if not (1 <= port <= 65535):
            errors.append('SMTP port must be between 1 and 65535')
    except (ValueError, TypeError):
        errors.append('SMTP port must be a valid integer')
    # Validate username
    if not settings.get('username', '').strip():
        errors.append('Mail username is required')
    # Validate password
    if not settings.get('password', '').strip():
        errors.append('Mail password is required')
    # Validate sender email
    sender = settings.get('sender_email', '').strip()
    if not sender:
        errors.append('Sender email is required')
    elif '@' not in sender or '.' not in sender.split('@')[-1]:
        errors.append('Sender email format is invalid')
    
    # Validate TLS/SSL mutual exclusivity
    use_tls = settings.get('use_tls', False)
    use_ssl = settings.get('use_ssl', False)
    port = int(settings.get('smtp_port', 587))
    
    # Enforce mutual exclusivity
    if use_tls and use_ssl:
        errors.append('Cannot enable both TLS and SSL. Use TLS for port 587, SSL for port 465.')
    
    # Warn about common misconfigurations
    if use_ssl and port == 587:
        errors.append('Port 587 typically requires TLS, not SSL')
    if use_tls and port == 465:
        errors.append('Port 465 typically requires SSL, not TLS')
        
    return errors

# --- EMAIL SETTINGS: GET ---
@settings_bp.route('/settings/email', methods=['GET'])
@auth_required()
@roles_accepted('admin')
def get_email_settings():
    """
    Get Email Notification Settings from SystemSettings (Admin Only)
    """
    # Get system-wide email settings
    settings = SystemSettings.query.filter_by(setting_key='email_notifications').first()
    email_settings = settings.setting_value if settings and settings.setting_value else {}
    
    # Decrypt password when retrieving (if it's encrypted)
    if 'password' in email_settings and email_settings['password']:
        if email_settings.get('is_encrypted', False):
            try:
                encryption_key = os.environ.get('EMAIL_PASSWORD_KEY')
                if not encryption_key:
                    return jsonify({'error': 'Server encryption not configured'}), 500
                f = Fernet(encryption_key.encode())
                decrypted_password = f.decrypt(email_settings['password'].encode()).decode()
                email_settings['password'] = decrypted_password
            except Exception as e:
                logging.error(f"Password decryption failed: {str(e)}")
                return jsonify({
                    'error': 'Password decryption failed. Please re-enter your credentials.',
                    'details': 'Encryption key may have changed or data is corrupted'
                }), 400
        # Remove internal flag before sending to frontend
        email_settings.pop('is_encrypted', None)

    return jsonify({'email_settings': email_settings}), 200

# --- EMAIL SETTINGS: SAVE ---
@settings_bp.route('/settings/email', methods=['POST'])
@auth_required()
@roles_accepted('admin')
def save_email_settings():
    """
    Save Email Notification Settings to SystemSettings (Admin Only)
    """
    data = request.get_json()
    email_settings = data.get('email_settings')
    
    if email_settings is None:
        return jsonify({'error': 'Email settings required'}), 400
    
    # Validate inputs
    validation_errors = validate_email_settings(email_settings)
    if validation_errors:
        return jsonify({'error': ', '.join(validation_errors)}), 400

    # Get existing system-wide settings to check if password has changed
    settings = SystemSettings.query.filter_by(setting_key='email_notifications').first()
    existing_email_settings = {}
    if settings and settings.setting_value:
        existing_email_settings = dict(settings.setting_value)

    # Encrypt password before saving if it's provided and different from existing
    if 'password' in email_settings and email_settings['password']:
        existing_password = existing_email_settings.get('password', '')
        existing_is_encrypted = existing_email_settings.get('is_encrypted', False)
        
        # If password is exactly the same as existing (unchanged), preserve existing encrypted value
        if email_settings['password'] == existing_password:
            # Password unchanged, preserve existing encrypted value
            email_settings['password'] = existing_password
            email_settings['is_encrypted'] = existing_is_encrypted
        elif email_settings['password']:
            # New password provided, encrypt it
            encryption_key = os.environ.get('EMAIL_PASSWORD_KEY')
            if not encryption_key:
                raise ValueError(
                    "EMAIL_PASSWORD_KEY environment variable must be set. "
                    "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                )
            f = Fernet(encryption_key.encode())
            email_settings['password'] = f.encrypt(email_settings['password'].encode()).decode()
            email_settings['is_encrypted'] = True

    # Create or update system settings
    if not settings:
        settings = SystemSettings(setting_key='email_notifications')
    settings.setting_value = email_settings
    settings.updated_by = current_user.id

    try:
        db.session.add(settings)
        db.session.commit()
        return jsonify({'message': 'Email settings saved successfully'}), 200
    except Exception as e:
        db.session.rollback()
        logging.exception("Failed to save email settings")
        return jsonify({'error': f'Failed to save email settings: {str(e)}'}), 500

# --- EMAIL SETTINGS: TEST ---
@settings_bp.route('/settings/email/test', methods=['POST'])
@auth_required()
@roles_accepted('admin')
def test_email_settings():
    """
    Test Email Notification Settings by sending a test email (Admin Only)
    """
    data = request.get_json()
    email_settings = data.get('email_settings')
    
    if not email_settings:
        return jsonify({'error': 'Email settings required'}), 400
    
    # Validate inputs
    validation_errors = validate_email_settings(email_settings)
    if validation_errors:
        return jsonify({'error': ', '.join(validation_errors)}), 400

    # Extract settings
    smtp_host = email_settings.get('smtp_host', 'smtp.gmail.com')
    smtp_port = int(email_settings.get('smtp_port', 587))
    use_tls = email_settings.get('use_tls', True)
    use_ssl = email_settings.get('use_ssl', False)
    username = email_settings.get('username', '')
    password = email_settings.get('password', '')
    sender_email = email_settings.get('sender_email', '')
    
    # Allow custom test recipient, default to current user
    test_recipient = data.get('test_recipient') or current_user.email
    if not test_recipient:
        return jsonify({'error': 'No valid recipient for test email'}), 400
        
    # Decrypt password if it's encrypted
    if password:
        if email_settings.get('is_encrypted', False):
            try:
                encryption_key = os.environ.get('EMAIL_PASSWORD_KEY')
                if not encryption_key:
                    return jsonify({'error': 'Server encryption not configured'}), 500
                f = Fernet(encryption_key.encode())
                decrypted_password = f.decrypt(password.encode()).decode()
                password = decrypted_password
            except Exception as e:
                logging.error(f"Password decryption failed in test: {str(e)}")
                return jsonify({
                    'error': 'Password decryption failed. Please re-enter your credentials.',
                    'details': 'Encryption key may have changed or data is corrupted'
                }), 400
        # If not encrypted, use password as is
    
    # Create message
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = test_recipient
    msg['Subject'] = "FleetOps Email Configuration Test"
    
    body = f"This is a test email from FleetOps sent to {test_recipient}. Your email notification settings are configured correctly."
    msg.attach(MIMEText(body, 'plain'))
    
    # Create SMTP connection with proper protocol selection
    # Auto-select protocol based on port if both/neither are set
    port = int(email_settings.get('smtp_port', 587))
    use_tls = email_settings.get('use_tls', True)
    use_ssl = email_settings.get('use_ssl', False)
    
    # Auto-adjust protocol based on port if there's a conflict
    if use_tls and use_ssl:
        # If both are set, prioritize based on port
        if port == 465:
            use_tls = False  # Use SSL for port 465
        else:
            use_ssl = False  # Use TLS for other ports (default to 587)
    elif not use_tls and not use_ssl:
        # If neither is set, auto-select based on port
        if port == 465:
            use_ssl = True
        else:
            use_tls = True  # Default to TLS for ports like 587
    
    # Create SMTP connection with timeout
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, port, timeout=10)
            if use_tls:
                server.starttls()
        
        # Login and send
        server.login(username, password)
        server.send_message(msg)
        server.quit()
        
        return jsonify({'message': f'Test email sent successfully to {test_recipient}!'}), 200
    except smtplib.SMTPAuthenticationError as e:
        return jsonify({'error': f'Authentication failed: {str(e)}. Check username and password.'}), 400
    except smtplib.SMTPConnectError as e:
        return jsonify({'error': f'Connection failed: {str(e)}. Check SMTP host and port.'}), 400
    except socket.timeout:
        return jsonify({'error': f'Connection timed out. Check SMTP host, port, and network connectivity.'}), 400
    except smtplib.SMTPException as e:
        return jsonify({'error': f'SMTP error: {str(e)}'}), 400
    except Exception as e:
        logging.exception("Unexpected error in test email")
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500
