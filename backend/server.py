import logging
import os
import sys
import traceback
from dotenv import load_dotenv
from flask_limiter.errors import RateLimitExceeded
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import jsonify
from flask_security.decorators import auth_required
from flask_security.utils import current_user

# Define valid roles as a constant to prevent race conditions and security issues
VALID_ROLES = {'admin', 'manager', 'accountant', 'customer', 'driver', 'guest', 'print'}

# Add libs directory to Python path to allow importing py_doc_generator
libs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'libs'))
if os.path.isdir(libs_path) and libs_path not in sys.path:
    sys.path.append(libs_path)

# Add py-doc-generator directory to Python path
py_doc_generator_path = os.path.join(libs_path, 'py-doc-generator')
if os.path.isdir(py_doc_generator_path) and py_doc_generator_path not in sys.path:
    sys.path.append(py_doc_generator_path)

# Load environment variables from .env file
load_dotenv()

env = os.environ.get('NODE_ENV', 'development')

from backend.config import DevConfig, StagingConfig, ProductionConfig
from backend.extensions import db, mail
from flask import Flask, jsonify, request, send_from_directory, abort


# Enhanced logging setup
BASEDIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASEDIR, 'logs')
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Import models - will be used later in app context
from backend.models.job_photo import JobPhoto
from backend.models.job import Job

# Logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, 'app.log')),
        logging.StreamHandler()
    ]
)
# Create a logger for this module
logger = logging.getLogger(__name__)

# Initialize app and extensions
app = Flask(__name__)
if env == 'production':
    app.config.from_object(ProductionConfig)
elif env == 'staging':
    app.config.from_object(StagingConfig)
else:
    # Instantiate DevConfig to trigger __init__ which sets up the database URI
    dev_config_instance = DevConfig()
    app.config.from_object(dev_config_instance)

# Configuration debug output - only in reloader process to avoid duplication
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    print("="*80)
    print("🔧 CONFIGURATION DEBUG")
    print("="*80)
    print(f"🌍 NODE_ENV: {env}")
    print(f"📦 Config Class Used: {ProductionConfig.__name__ if env == 'production' else StagingConfig.__name__ if env == 'staging' else DevConfig.__name__}")
    print(f"🗄️  SQLALCHEMY_DATABASE_URI: {app.config.get('SQLALCHEMY_DATABASE_URI', 'NOT SET!')}")
    print(f"🐛 DEBUG: {app.config.get('DEBUG', 'NOT SET')}")
    print(f"🌐 FLASK_HOST: {app.config.get('FLASK_HOST', 'NOT SET')}")
    print(f"🔗 FRONTEND_URL: {app.config.get('FRONTEND_URL', 'NOT SET')}")
    print(f"🍪 SESSION_COOKIE_SECURE: {app.config.get('SESSION_COOKIE_SECURE', 'NOT SET')}")
    print("="*80)

# Add Flask-Security-Too configuration
app.config['SECURITY_URL_PREFIX'] = '/api/auth'
app.config['SECURITY_POST_LOGIN_VIEW'] = '/dashboard'  # Changed from '/api/auth/me' to prevent redirect loop
app.config['SECURITY_POST_LOGOUT_VIEW'] = '/login'     # Changed from '/api/auth/login' to prevent redirect loop
app.config['SECURITY_POST_REGISTER_VIEW'] = '/login'

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["1000 per day", "500 per hour"]
)

# Debug: Print database configuration
logger.info(f"App working directory: {os.getcwd()}")
logger.info("Database connected: %s", "sqlite" if "sqlite" in app.config.get("SQLALCHEMY_DATABASE_URI","") else "non-sqlite")

# Ensure folders exist
try:
    os.makedirs(app.config['JOB_PHOTO_UPLOAD_FOLDER'], exist_ok=True)
    logger.info(f"Upload folder created/verified: {app.config['JOB_PHOTO_UPLOAD_FOLDER']}")
except Exception as e:
    logger.error(f"Failed to create upload folder: {e}")

# Initialize extensions with proper error handling
try:
    db.init_app(app)
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"CRITICAL: Failed to initialize database: {e}")
    logger.error(traceback.format_exc())
    raise  # Stop the app - don't continue with broken DB

try:
    mail.init_app(app)
    logger.info("Mail initialized successfully")
except Exception as e:
    logger.error(f"WARNING: Failed to initialize mail: {e}")
    logger.error("App will continue, but password reset emails won't work")
    # Don't raise for mail - app can work without it

# Initialize scheduler for background tasks
try:
    from backend.services.scheduler_service import scheduler_service
    scheduler_service.start()
    logger.info("Scheduler service initialized successfully")
except Exception as e:
    logger.error(f"WARNING: Failed to initialize scheduler: {e}")
    logger.error("App will continue, but scheduled tasks won't run")

# Configure CORS for better proxy support
CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": [
    "https://localhost",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:8100",
    "http://127.0.0.1:8100",
    "https://test.grepx.sg",
    "https://fleet.avant-garde.com.sg/",
    "capacitor://localhost",
    "ionic://localhost",
    "http://ec2-47-130-215-5.ap-southeast-1.compute.amazonaws.com:3000",
    "http://ec2-52-76-147-189.ap-southeast-1.compute.amazonaws.com:3000"
]}})

@app.after_request
def add_cors_headers(response):
    allowed_origins = [
        "http://localhost:3000",
        "https://test.grepx.sg",
        "https://fleet.avant-garde.com.sg/"
    ]
    origin = request.headers.get('Origin')
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept"
    return response

# Custom login logging function
def log_authentication_details(email, provided_password, user_obj=None):
    logger.info("="*80)
    logger.info("AUTH DEBUG")
    logger.info("="*80)
    logger.info(f"Email: '{email}'")
    logger.info(f"Provided password present: {bool(provided_password)}")

    if user_obj:
        logger.info("User found in DB: YES")
        logger.info(f"User ID: {user_obj.id}")
        logger.info(f"User active: {getattr(user_obj, 'active', None)}")

        try:
            from flask_security.utils import verify_password
            ok = verify_password(provided_password or "", getattr(user_obj, "password", "") or "")
            logger.info(f"Password verify (boolean): {bool(ok)}")
        except Exception as e:
            logger.info(f"Password verify failed: {e}")
    else:
        logger.info("User found in DB: NO")
    logger.info("="*80)


# Import models and Flask-Security-Too setup after app/db are ready
with app.app_context():
    # Import all models with clear error handling
    try:
        from backend.models import (
            user, role, customer, sub_customer, vehicle, driver,
            job, invoice, password_reset_token, contractor,
            contractor_service_pricing, driver_leave, leave_override
        )
        logger.info("Models imported successfully")
    except ImportError as e:
        logger.error(f"CRITICAL: Failed to import models: {e}")
        logger.error(traceback.format_exc())
        raise  # Stop the app - can't work without models
    
    # Initialize Flask-Security with clear error handling
    try:
        from flask_security.core import Security
        from flask_security.datastore import SQLAlchemyUserDatastore
        from backend.models.user import User
        from backend.models.role import Role
        
        user_datastore = SQLAlchemyUserDatastore(db, User, Role)
        security = Security(app, user_datastore)
        logger.info("Flask-Security initialized successfully")

        # Initialize login security (account lockout, failed login tracking)
        from backend.services.login_security import init_login_security
        init_login_security(app)
        logger.info("Login security handlers initialized successfully")
        
        # Logging patch
        original_find_user = user_datastore.find_user
        def logged_find_user(*args, **kwargs):
            result = original_find_user(*args, **kwargs)
            if 'email' in kwargs:
                email = kwargs['email']
                logger.info(f"[SEARCH] User lookup for email: '{email}' -> {'Found' if result else 'Not Found'}")
            return result
        user_datastore.find_user = logged_find_user
        
    except Exception as e:
        logger.error(f"CRITICAL: Failed to initialize Flask-Security: {e}")
        logger.error(traceback.format_exc())
        raise  # Stop the app - can't work without security

# Register blueprints
blueprints = [
    ('example', '/api'),
    ('customer', '/api'),
    ('job', '/api'),
    ('driver', '/api'),
    ('vehicle', '/api'),
    ('vehicle_type', '/api'),
    ('invoice', '/api'),
    ('sub_customer', '/api'),
    ('user', '/api/auth'),
    ('role', '/api'),
    ('service', '/api'),
    ('customer_service_pricing', '/api'),
    ('chat', '/api'),
    ('settings', '/api'),
    ('admin', '/api/admin'),
    ('db_export', '/api'),
    ('contractor', '/api'),
    ('services_vehicle_type_price', '/api'),
    ('bill', '/api'),
    ('reports', '/api'),
    ('driver_leave', '/api'),
    ('leave_override', '/api'),
    ('pipeline', '/api')
]

for blueprint_name, prefix in blueprints:
    try:
        module = __import__(f'backend.api.{blueprint_name}', fromlist=[f'{blueprint_name}_bp'])
        blueprint = getattr(module, f'{blueprint_name}_bp')
        app.register_blueprint(blueprint, url_prefix=prefix)
        logger.info(f"Registered blueprint: {blueprint_name} with prefix: {prefix}")
        
        # Initialize limiter for all blueprints that have init_app function
        if hasattr(module, 'init_app'):
            module.init_app(app)
            logger.info(f"Initialized rate limiter for blueprint: {blueprint_name}")
    except (ImportError, AttributeError) as e:
        logger.error(f"Could not import {blueprint_name} blueprint: {e}")

# Register mobile driver blueprint
try:
    # Import module and initialize limiter BEFORE blueprint import
    import backend.api.mobileapi.driver as mobile_driver_module
    if not hasattr(mobile_driver_module, 'init_app'):
        raise RuntimeError("mobile_driver module missing required init_app function for rate limiting")
    mobile_driver_module.init_app(app)  # Initialize limiter before blueprint registration
    
    # Now import and register blueprint safely
    from backend.api.mobileapi.driver import mobile_driver_bp
    app.register_blueprint(mobile_driver_bp, url_prefix='/api/mobile')
    logger.info("Mobile driver blueprint registered successfully with rate limiting")
except Exception as e:
    logger.error(f"Error while registering mobile driver blueprint: {e}", exc_info=True)

# Request logging middleware
@app.before_request
def log_request_info():
    logger.debug(f"Request: {request.method} {request.url}")
    logger.debug(f"Headers: {dict(request.headers)}")
    if request.is_json and request.content_length:
        request_data = request.get_json(silent=True)
        logger.debug(f"JSON data: {request_data}")

        # Special handling for login requests - log authentication details
        if (request.endpoint and 'login' in str(request.endpoint).lower() and
            request_data and 'email' in request_data and 'password' in request_data):
            email = request_data.get('email')
            password = request_data.get('password')

            # Find user in database for detailed comparison
            try:
                from backend.models.user import User
                user_obj = User.query.filter_by(email=email).first()
                log_authentication_details(email, password, user_obj)
            except Exception as e:
                logger.error(f"Error during authentication logging: {e}")
                logger.error(traceback.format_exc())

    elif request.form:
        form_data = dict(request.form)
        logger.debug(f"Form data: {form_data}")

        if (request.endpoint and 'login' in str(request.endpoint).lower() and
            'email' in form_data and 'password' in form_data):
            email = form_data.get('email')
            password = form_data.get('password')

            try:
                from backend.models.user import User
                user_obj = User.query.filter_by(email=email).first()
                log_authentication_details(email, password, user_obj)
            except Exception as e:
                logger.error(f"Error during authentication logging: {e}")
                logger.error(traceback.format_exc())

@app.after_request
def log_response_info(response):
    logger.debug(f"Response: {response.status_code}")
    if response.status_code >= 400:
        logger.error(f"Error response: {response.status_code} for {request.method} {request.url}")
        if response.is_json:
            response_data = response.get_json()
            logger.error(f"Response data: {response_data}")

            # Log additional details for authentication failures
            if (request.endpoint and 'login' in str(request.endpoint).lower() and
                response.status_code == 400):
                logger.error("🚨 LOGIN FAILURE DETECTED 🚨")
                if response_data and 'response' in response_data:
                    errors = response_data['response'].get('errors', [])
                    field_errors = response_data['response'].get('field_errors', {})
                    logger.error(f"🚨 Errors: {errors}")
                    logger.error(f"🚨 Field errors: {field_errors}")
        else:
            logger.error(f"Response data: {response.get_data(as_text=True)}")
    return response

@app.before_request
def log_request_origin():
    origin = request.headers.get("Origin")
    if origin:
        logger.info(f"[CORS DEBUG] Incoming request Origin: {origin}")
    else:
        logger.info("[CORS DEBUG] No Origin header present in request")


@app.route('/')
def root():
    return {'status': 'ok', 'message': 'FleetWise Backend API is running. Available endpoints: /api/*'}

@app.route('/api/health-check')
def health_check():
    return {'status': 'ok', 'message': 'Backend for Next.js is running.'}

@app.route('/api/navigation')
@auth_required()
def navigation_permissions():
    """Return navigation permissions for the current user based on their roles."""
    try:
        user_roles = [role.name for role in current_user.roles]
        
        # Define navigation restrictions based on roles
        blocked_nav = []
        
        # Example: Non-admin users may have restricted access to certain admin functions
        if not any(role in user_roles for role in ['admin', 'manager']):
            # Block admin-specific routes for non-admin users
            blocked_nav.extend([
                '/admin/*',
                '/settings/*',  # Some settings may be restricted
                '/billing/contractor-billing',  # May be restricted based on role
            ])
            
            # Non-admin users may have limited access to some driver functions
            if 'driver' not in user_roles:  # For non-driver users who aren't admin/manager
                blocked_nav.extend([
                    '/drivers/leave/apply',  # Only drivers should apply for leave
                ])
        
        # Drivers have limited navigation
        if 'driver' in user_roles:
            blocked_nav.extend([
                '/jobs/manage',
                '/billing/*',
                '/admin/*',
                '/reports/driver',  # Maybe drivers shouldn't see all reports
                '/customers',
                '/drivers',  # Block main drivers page
                '/drivers/new',  # Drivers shouldn't create new drivers
                '/drivers/edit',  # Drivers shouldn't edit other drivers
                '/drivers/leave',  # Drivers should use specific leave apply route
                '/drivers/calendar',  # Block driver calendar access - only for admin/manager
                # Add more specific restrictions as needed
            ])
        
        # Print role is already included in VALID_ROLES constant
        
        # Handle print role access
        if 'print' in user_roles:
            # Print role may need access to specific print-related functionality
            # For now, don't block anything specifically for print role
            pass
        
        # Customers have very limited navigation
        if 'customer' in user_roles:
            blocked_nav.extend([
                '/jobs/manage',
                '/billing/*',
                '/admin/*',
                '/drivers',  # Customers don't need to see driver management
                '/vehicles',
                '/reports/*',
                '/jobs/new',
                '/jobs/bulk-upload',
                '/jobs/audit-trail',
                # Block other job-related pages that aren't relevant to customers
                '/jobs/manage/*',
                '/jobs/audit-trail/*',
            ])
            
            # Specific customer restrictions
            blocked_nav.extend([
                '/drivers/leave/apply',  # Only drivers can apply for leave
            ])
            
            # Ensure customer dashboard is accessible - remove any potential blocks
            # The customer dashboard should be available to customers
            # Don't add /jobs/dashboard/* to blocked list for customers
        
        # No special handling needed for drivers since calendar access is explicitly blocked above
        
        # Log the blocked navigation for debugging
        logger.info(f"User {current_user.email} (roles: {user_roles}) has blocked navigation: {blocked_nav}")
        return jsonify({'blockedNav': blocked_nav})
    except Exception as e:
        logger.error(f"Error in navigation permissions: {e}", exc_info=True)
        # Fail secure - block all routes on error
        return jsonify({
            'error': 'Failed to determine permissions',
            'blockedNav': ['/*']  # Block everything
        }), 500


@app.route("/api/auth/me", methods=["GET"])
@auth_required()
def auth_me():
    try:
        roles = [
            {"id": r.id, "name": r.name.lower()}
            for r in (current_user.roles or [])
        ]
        
        primary_role = roles[0]["name"] if roles else "guest"
        
        # Print user roles for debugging
        user_roles = [role.name for role in current_user.roles]
        logger.info(f"User {current_user.email} (ID: {current_user.id}) has roles: {user_roles}")
        
        # Validate role name
        if primary_role not in VALID_ROLES:
            logger.warning(
                f"Invalid role '{primary_role}' for user {current_user.id}, defaulting to guest"
            )
            primary_role = "guest"
        
        return jsonify({
            "response": {
                "user": {
                    "id": current_user.id,
                    "email": current_user.email,
                    "role": primary_role,  
                    "roles": roles        
                }
            }
        }), 200

    except Exception as e:
        logger.error(f"/api/auth/me error: {e}", exc_info=True)
        return jsonify({"error": "unexpected"}), 500

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception for {request.method} {request.url}: {e}")
    logger.error(traceback.format_exc())
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(400)
def bad_request(error):
    logger.error(f"400 Bad Request for {request.method} {request.url}")
    logger.error(f"Request data: {request.get_data(as_text=True)}")
    logger.error(f"Error: {error}")
    return jsonify({
        'error': 'Bad Request',
        'message': str(error),
        'path': request.path
    }), 400
# Custom error handler for Flask-Security-Too to return JSON
@app.errorhandler(401)
def unauthorized(error):
    logger.error(f"401 Unauthorized for {request.method} {request.url}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Authentication required'}), 401
    return error

@app.errorhandler(403)
def forbidden(error):
    logger.error(f"403 Forbidden for {request.method} {request.url}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Access forbidden'}), 403
    return error

@app.errorhandler(404)
def not_found(error):
    logger.error(f"404 error for path: {request.path}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found', 'path': request.path}), 404
    return jsonify({'error': 'Page not found', 'path': request.path}), 404

@app.errorhandler(RateLimitExceeded)
def ratelimit_handler(e):
    logger.warning(f"Rate limit exceeded for {request.method} {request.url}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
    return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429

@app.route('/uploads/job_photos/<filename>')
def uploaded_file(filename):
    """
    Secure and optimized photo access endpoint that addresses TOCTOU vulnerabilities and performance issues.

    This endpoint:
    - Uses a single atomic query with eager loading to verify all relationships
    - Eliminates the TOCTOU gap and reduces database round-trips
    - Supports both old paths (temporary uploads) and new paths (fleetwise-storage)
    - Automatically serves photos from their stored location
    """
    # All photo access requires authentication
    if not current_user or not hasattr(current_user, 'has_role'):
        abort(403)

    try:
        # Parse filename to get job_id (format: job_id_driver_id_stage_timestamp.jpg)
        parts = filename.split('_')
        if len(parts) < 2:
            abort(404)
        job_id = int(parts[0])
        # Note: We don't trust the driver_id from filename for authorization checks

        # Admins and managers can access all photos
        if current_user.has_role('admin') or current_user.has_role('manager'):
            # Single atomic query with eager-loaded relationship for admins/managers
            from sqlalchemy.orm import joinedload
            photo = JobPhoto.query.options(
                joinedload(JobPhoto.job)
            ).filter(
                JobPhoto.job_id == job_id,
                JobPhoto.filename == filename  # Use exact matching instead of endswith for better performance
            ).first()

            # Atomically verify photo exists and job relationship is valid
            if not photo or not photo.job:
                abort(404)
        # Drivers can access photos from jobs they own
        elif hasattr(current_user, 'driver_id'):
            # Single atomic query with eager-loaded relationship for drivers
            from sqlalchemy.orm import joinedload
            photo = JobPhoto.query.options(
                joinedload(JobPhoto.job)
            ).filter(
                JobPhoto.job_id == job_id,
                JobPhoto.driver_id == current_user.driver_id,
                JobPhoto.filename == filename  # Use exact matching instead of endswith for better performance
            ).first()

            # Atomically verify photo exists and job relationship is valid
            if not photo or not photo.job or photo.job.driver_id != current_user.driver_id:
                abort(403)
        else:
            # For other authenticated users, verify job ownership using their driver_id
            user_driver_id = getattr(current_user, 'driver_id', None)
            if not user_driver_id:
                abort(403)

            # Single atomic query with eager-loaded relationship
            from sqlalchemy.orm import joinedload
            photo = JobPhoto.query.options(
                joinedload(JobPhoto.job)
            ).filter(
                JobPhoto.job_id == job_id,
                JobPhoto.driver_id == user_driver_id,
                JobPhoto.filename == filename  # Use exact matching instead of endswith for better performance
            ).first()

            # Atomically verify photo exists and job relationship is valid
            if not photo or not photo.job or photo.job.driver_id != user_driver_id:
                abort(403)

    except (ValueError, IndexError):
        abort(404)

    # Determine photo location: from file_path in database
    # file_path can be:
    # - Old format: absolute path to temp folder (backward compatibility)
    # - New format: relative path like "images/2025/11/07/filename.jpg" (fleetwise-storage root)
    if photo.file_path:
        file_path = photo.file_path

        # Check if it's a relative path (new format from fleetwise-storage)
        if not os.path.isabs(file_path):
            # Relative path - construct full path from fleetwise-storage root (parent of PHOTO_STORAGE_ROOT)
            photo_storage_root = app.config.get('PHOTO_STORAGE_ROOT')
            if photo_storage_root:
                # PHOTO_STORAGE_ROOT points to "fleetwise-storage/images"
                # file_path is relative to "fleetwise-storage" (includes "images/2025/...")
                # So we get parent of PHOTO_STORAGE_ROOT to get fleetwise-storage root
                fleetwise_storage_root = os.path.dirname(photo_storage_root)
                full_path = os.path.join(fleetwise_storage_root, file_path)

                if os.path.exists(full_path):
                    return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))
        else:
            # Absolute path - check if it exists
            if os.path.exists(file_path):
                return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path))

    # Fallback to old upload folder for backward compatibility
    upload_folder = app.config.get('JOB_PHOTO_UPLOAD_FOLDER')
    if upload_folder and os.path.exists(os.path.join(upload_folder, filename)):
        return send_from_directory(upload_folder, filename)

    # Photo file not found
    logger.warning(f"Photo file not found for job_id={job_id}, filename={filename}")
    abort(404)


if __name__ == '__main__':
    host = app.config.get('FLASK_HOST', '0.0.0.0')
    port = app.config.get('FLASK_PORT', 5000)
    debug = app.config.get('DEBUG', True)
    
    logger.info(f"Starting Flask app on {host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)

   
