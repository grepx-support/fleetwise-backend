import logging
import os
import sys
import traceback
from dotenv import load_dotenv
from flask_limiter.errors import RateLimitExceeded
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Load environment variables from .env file
load_dotenv()

# Add the current directory to Python path to fix import issues
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# Try different import paths for config
try:
    from backend.config import DevConfig
except ImportError:
    try:
        from config import DevConfig
    except ImportError:
        # Fallback config
        class DevConfig:
            SECRET_KEY = 'dev-secret-key'
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            BASEDIR = os.path.dirname(os.path.abspath(__file__))
            DB_PATH = os.path.join(BASEDIR, 'app.db')
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
            DEBUG = True
            JOB_PHOTO_UPLOAD_FOLDER = os.path.join(BASEDIR, 'static', 'uploads')

# Try different import paths for extensions
try:
    from backend.extensions import db, mail
except ImportError:
    try:
        from extensions import db, mail
    except ImportError:
        # Fallback: create db instance directly
        try:
            from flask_sqlalchemy import SQLAlchemy
            from flask_mail import Mail
            db = SQLAlchemy()
            mail = Mail()
        except:
            db = None
            mail = None

from flask import Flask, jsonify, request, send_from_directory, abort
try:
    from flask_security.decorators import auth_required
    from flask_security.utils import current_user
except ImportError:
    # Fallback for flask_security
    def auth_required():
        def decorator(f):
            return f
        return decorator
    current_user = None
# Enhanced logging setup
BASEDIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASEDIR, 'logs')
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)


# Import JobPhoto and Job models for secure photo access
try:
    from backend.models.job_photo import JobPhoto
    from backend.models.job import Job
except ImportError:
    try:
        from models.job_photo import JobPhoto
        from models.job import Job
    except ImportError:
        JobPhoto = None
        Job = None

# Logging setup
BASEDIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASEDIR, 'logs')
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)
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
app.config.from_object(DevConfig)

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
# print(f"App working directory: {os.getcwd()}")
# print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

# Debug: Print database configuration
logger.info(f"App working directory: {os.getcwd()}")
logger.info("Database connected: %s", "sqlite" if "sqlite" in app.config.get("SQLALCHEMY_DATABASE_URI","") else "non-sqlite")


# Ensure folders exist
try:
    os.makedirs(app.config['JOB_PHOTO_UPLOAD_FOLDER'], exist_ok=True)
    logger.info(f"Upload folder created/verified: {app.config['JOB_PHOTO_UPLOAD_FOLDER']}")
except Exception as e:
    logger.error(f"Failed to create upload folder: {e}")

if db:
    try:
        db.init_app(app)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Warning: Could not initialize database: {e}")


if mail:
    try:
        mail.init_app(app)
        logger.info("Mail initialized successfully")
    except Exception as e:
        logger.error(f"Warning: Could not initialize mail: {e}")

# Configure CORS for better proxy support
# CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": "*"}})
#CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": ["https://localhost","http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001", "http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:8100", "http://127.0.0.1:8100","https://test.grepx.sg","capacitor://localhost","ionic://localhost"]}})

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
    "capacitor://localhost",
    "ionic://localhost",
    "http://ec2-18-143-75-251.ap-southeast-1.compute.amazonaws.com:3000",
    "http://ec2-47-129-134-106.ap-southeast-1.compute.amazonaws.com:3001"  # Add this!
]}})

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
    # Try different import paths
    try:
        # Import all model classes directly to ensure proper relationship setup
        from backend.models.user import User
        from backend.models.role import Role
        from backend.models.customer import Customer
        from backend.models.sub_customer import SubCustomer
        from backend.models.vehicle import Vehicle
        from backend.models.driver import Driver
        from backend.models.job import Job
        from backend.models.invoice import Invoice
        from backend.models.password_reset_token import PasswordResetToken
        from backend.models.contractor import Contractor
        from backend.models.contractor_service_pricing import ContractorServicePricing
        from backend.models.service import Service
        from backend.models.customer_service_pricing import CustomerServicePricing
        from backend.models.vehicle_type import VehicleType
        from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice
        from backend.models.driver_remark import DriverRemark
        from backend.models.job_photo import JobPhoto
        from backend.models.postal_code import PostalCode
        from backend.models.job_audit import JobAudit
        from backend.models.settings import UserSettings
        logger.info("Models imported successfully from backend.models")
        
        try:
            from flask_security.core import Security
            from flask_security.datastore import SQLAlchemyUserDatastore
            if db is not None:
                user_datastore = SQLAlchemyUserDatastore(db, User, Role)
                security = Security(app, user_datastore)
                logger.info("Flask-Security initialized successfully")
                # Monkey patch the user datastore to add logging
                original_find_user = user_datastore.find_user
                def logged_find_user(*args, **kwargs):
                    result = original_find_user(*args, **kwargs)
                    if 'email' in kwargs:
                        email = kwargs['email']
                        logger.info(f"[SEARCH] User lookup for email: '{email}' -> {'Found' if result else 'Not Found'}")
                    return result
                user_datastore.find_user = logged_find_user
        except Exception as e:
            logger.error(f"Warning: Could not initialize Flask-Security: {e}")
            logger.error(traceback.format_exc())
    except ImportError as e:
        logger.warning(f"Failed to import from backend.models: {e}")
        try:
            # Fallback: import from models package
            from models.user import User
            from models.role import Role
            from models.customer import Customer
            from models.sub_customer import SubCustomer
            from models.vehicle import Vehicle
            from models.driver import Driver
            from models.job import Job
            from models.invoice import Invoice
            from models.password_reset_token import PasswordResetToken
            from models.contractor import Contractor
            from models.contractor_service_pricing import ContractorServicePricing
            logger.info("Models imported successfully from models")
            
            try:
                from flask_security.core import Security
                from flask_security.datastore import SQLAlchemyUserDatastore
                if db is not None:
                    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
                    security = Security(app, user_datastore)
                    logger.info("Flask-Security initialized successfully")

                    # Monkey patch the user datastore to add logging
                    original_find_user = user_datastore.find_user
                    def logged_find_user(*args, **kwargs):
                        result = original_find_user(*args, **kwargs)
                        if 'email' in kwargs:
                            email = kwargs['email']
                            logger.info(f"[SEARCH] User lookup for email: '{email}' -> {'Found' if result else 'Not Found'}")
                        return result
                    user_datastore.find_user = logged_find_user
            except Exception as e:
                logger.error(f"Warning: Could not initialize Flask-Security: {e}")
                logger.error(traceback.format_exc())
        except ImportError as e:
            logger.error(f"Warning: Could not import all models: {e}")
            

# Register blueprints with fallback import handling
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
    ('services_vehicle_type_price', '/api')
]

for blueprint_name, prefix in blueprints:
    try:
        module = __import__(f'backend.api.{blueprint_name}', fromlist=[f'{blueprint_name}_bp'])
        blueprint = getattr(module, f'{blueprint_name}_bp')
        app.register_blueprint(blueprint, url_prefix=prefix)
        logger.info(f"Registered blueprint: {blueprint_name} with prefix: {prefix}")
        #print(f"Registered blueprint: {blueprint_name} with prefix: {prefix}")
        # Initialize limiter for all blueprints that have init_app function
        if hasattr(module, 'init_app'):
            module.init_app(app)
            print(f"Initialized rate limiter for blueprint: {blueprint_name}")
    except ImportError as e:
        logger.warning(f"Failed to import from backend.api.{blueprint_name}: {e}")
        try:
            module = __import__(f'api.{blueprint_name}', fromlist=[f'{blueprint_name}_bp'])
            blueprint = getattr(module, f'{blueprint_name}_bp')
            app.register_blueprint(blueprint, url_prefix=prefix)
            logger.info(f"Registered blueprint: {blueprint_name} with prefix: {prefix}")
            # Initialize limiter for all blueprints that have init_app function
            if hasattr(module, 'init_app'):
                module.init_app(app)
                print(f"Initialized rate limiter for blueprint: {blueprint_name}")
        except ImportError as e:
            logger.error(f"Warning: Could not import {blueprint_name} blueprint: {e}")
try:
    # Import module and initialize limiter BEFORE blueprint import
    import backend.api.mobileapi.driver as mobile_driver_module
    if not hasattr(mobile_driver_module, 'init_app'):
        raise RuntimeError("mobile_driver module missing required init_app function for rate limiting")
    mobile_driver_module.init_app(app)  # Initialize limiter before blueprint registration
    
    # Now import and register blueprint safely
    from backend.api.mobileapi.driver import mobile_driver_bp
    app.register_blueprint(mobile_driver_bp, url_prefix='/api/mobile')
    logging.info("Mobile driver blueprint registered successfully with rate limiting")
except ImportError as e:
    logging.error(f"Failed to import mobile driver blueprint: {e}", exc_info=True)
    logger.error(traceback.format_exc())
except Exception as e:
    logging.error(f"Unexpected error while registering mobile driver blueprint: {e}", exc_info=True)
    logger.error(traceback.format_exc())

# Add request logging middleware

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
                # Import User model
                try:
                    from backend.models.user import User
                except ImportError:
                    from models.user import User

                user_obj = User.query.filter_by(email=email).first()
                log_authentication_details(email, password, user_obj)

            except Exception as e:
                logger.error(f"Error during authentication logging: {e}")
                logger.error(traceback.format_exc())

    elif request.form:
        form_data = dict(request.form)
        logger.debug(f"Form data: {form_data}")

        # Handle form-based login too
        if (request.endpoint and 'login' in str(request.endpoint).lower() and
            'email' in form_data and 'password' in form_data):

            email = form_data.get('email')
            password = form_data.get('password')

            try:
                # Import User model
                try:
                    from backend.models.user import User
                except ImportError:
                    from models.user import User

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


from flask import request
@app.before_request
def log_request_origin():
    origin = request.headers.get("Origin")
    if origin:
        print(f"[CORS DEBUG] Incoming request Origin: {origin}")
        logging.info(f"[CORS DEBUG] Incoming request Origin: {origin}")
    else:
        print("[CORS DEBUG] No Origin header present in request")
        logging.info("[CORS DEBUG] No Origin header present in request")


@app.route('/')
def root():
    return {'status': 'ok', 'message': 'FleetWise Backend API is running. Available endpoints: /api/*'}

@app.route('/api/health-check')
def health_check():
    return {'status': 'ok', 'message': 'Backend for Next.js is running.'}

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.errorhandler(404)
def not_found(error):
    logger.error(f"404 error for path: {request.path}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found', 'path': request.path}), 404
    return jsonify({'error': 'Page not found', 'path': request.path}), 404

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception for {request.method} {request.url}: {e}")
    logger.error(traceback.format_exc())
    #logging.error(f"Unhandled exception: {e}", exc_info=True)
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
    
    This endpoint uses a single atomic query with eager loading to verify all relationships 
    simultaneously, eliminating the TOCTOU gap and reducing database round-trips.
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
 
    return send_from_directory(app.config['JOB_PHOTO_UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(host="::", port=5000, debug=True) 