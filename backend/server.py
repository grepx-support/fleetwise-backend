import logging
import os
import sys
import traceback
import threading
import time
from datetime import datetime
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


# Enhanced logging setup with rotation
import logging.handlers

# Import enhanced logging components
from backend.utils.system_monitor import start_system_monitoring, stop_system_monitoring
from backend.utils.request_logger import RequestLogger

# Resource monitoring configuration
RESOURCE_MONITORING_INTERVAL = 60  # Check every 60 seconds
HIGH_MEMORY_THRESHOLD = 80.0  # Percentage
HIGH_CPU_THRESHOLD = 80.0     # Percentage
HIGH_DB_POOL_THRESHOLD = 80.0 # Percentage
HIGH_THREAD_THRESHOLD = 100   # Thread count

# Circuit breaker configuration
CIRCUIT_BREAKER_ENABLED = True
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_TIMEOUT = 60  # Seconds

BASEDIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASEDIR, 'logs')
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Import models - will be used later in app context
from backend.models.job_photo import JobPhoto
from backend.models.job import Job

# Configure rotating file handlers
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')

# Main application log with rotation (50MB per file, keep 10 files)
app_log_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOGS_DIR, 'app.log'),
    maxBytes=50*1024*1024,  # 50MB
    backupCount=10
)
app_log_handler.setFormatter(log_formatter)
app_log_handler.setLevel(logging.INFO)

# Error log with rotation (separate file for errors)
error_log_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOGS_DIR, 'error.log'),
    maxBytes=50*1024*1024,  # 50MB
    backupCount=10
)
error_log_handler.setFormatter(log_formatter)
error_log_handler.setLevel(logging.ERROR)

# Console handler (will be configured after app initialization)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# Configure root logger - INFO level for production, DEBUG for development
root_logger = logging.getLogger()
# Use INFO level in production to reduce logging overhead
root_logger.setLevel(logging.INFO if env in ['production', 'staging'] else logging.DEBUG)

# Prevent handler duplication on reload
if not root_logger.handlers:
    root_logger.addHandler(app_log_handler)
    root_logger.addHandler(error_log_handler)
    root_logger.addHandler(console_handler)

# Create a logger for this module
logger = logging.getLogger(__name__)

# Log startup information
logger.info("=" * 80)
logger.info("Application startup")
logger.info(f"Log directory: {LOGS_DIR}")
logger.info(f"Log file rotation: 50MB max size, 10 backup files")
logger.info("=" * 80)

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

# Configure console handler level based on app debug setting
console_handler.setLevel(logging.DEBUG if app.config.get('DEBUG', False) else logging.INFO)

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

# Configure request logging
app.before_request(RequestLogger.before_request)
app.after_request(RequestLogger.after_request)

# Initialize scheduler for background tasks - only in main process
try:
    # Only start scheduler if explicitly enabled or in main Flask process
    is_main_process = (os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or 
                      os.environ.get('ENABLE_SCHEDULER') == 'true')
    
    if is_main_process:
        from backend.services.scheduler_service import scheduler_service
        scheduler_service.start()
        logger.info("Scheduler service initialized successfully in main process")
    else:
        logger.info("Scheduler service disabled - not in main process or scheduler not enabled")
    
    # Start system monitoring
    start_system_monitoring()
    logger.info("System monitoring started")
    
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
    ('pipeline', '/api'),
    ('job_monitoring', '/api'),
    ('frontend_logs', '/api')
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

# Request logging middleware - reduced verbosity in production
@app.before_request
def log_request_info():
    # Only log request details in development/debug mode
    if app.config.get('DEBUG', False):
        logger.debug(f"Request: {request.method} {request.url}")
        logger.debug(f"Headers: {dict(request.headers)}")
        if request.is_json and request.content_length:
            request_data = request.get_json(silent=True)
            logger.debug(f"JSON data: {request_data}")

        # Special handling for login requests - log authentication details (development only)
        if (app.config.get('DEBUG', False) and 
            request.endpoint and 'login' in str(request.endpoint).lower() and
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
                logger.error("LOGIN FAILURE DETECTED")
                if response_data and 'response' in response_data:
                    errors = response_data['response'].get('errors', [])
                    field_errors = response_data['response'].get('field_errors', {})
                    logger.error(f"Errors: {errors}")
                    logger.error(f"Field errors: {field_errors}")
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

import psutil
import gc

@app.route('/api/health-check')
def health_check():
    """Lightweight health check endpoint for load balancers and uptime monitors."""
    try:
        # Minimal health check - fast and cheap
        # Just verify app is responding, don't do expensive operations
        return {'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}, 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {'status': 'error', 'message': 'Service unhealthy'}, 503

@app.route('/api/diagnostics')
def diagnostics_check():
    """Heavy diagnostics endpoint - for manual inspection only."""
    try:
        # Expensive health check with full system diagnostics
        # Quick database connectivity check
        db_healthy = db.health_check()
        
        if db_healthy:
            return {'status': 'ok', 'message': 'Backend is healthy'}, 200
        else:
            return {'status': 'error', 'message': 'Database connection unhealthy'}, 503
    except Exception as e:
        logger.error(f"Diagnostics check failed: {e}")
        return {'status': 'error', 'message': 'Service unhealthy'}, 503

@app.route('/api/system-health')
def system_health():
    """Comprehensive system health check endpoint."""
    try:
        # Database health
        db_health = db.health_check()
        db_stats = db.get_pool_stats() if hasattr(db, 'get_pool_stats') else {}
        
        # Memory usage
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()
        
        # CPU usage
        cpu_percent = process.cpu_percent(interval=0.1)
        
        # Thread count
        thread_count = process.num_threads()
        
        # File descriptors (Unix only)
        try:
            fd_count = process.num_fds()
        except AttributeError:
            fd_count = None  # Windows doesn't have file descriptors
        
        # Garbage collector stats
        gc_stats = gc.get_stats()
        
        # Scheduler health (if available)
        scheduler_health = False
        scheduler_stats = {}
        try:
            from backend.services.scheduler_service import scheduler_service
            scheduler_health = scheduler_service.health_check()
            scheduler_stats = scheduler_service.get_stats()
        except Exception as e:
            logger.debug(f"Scheduler health check unavailable: {e}")
        
        # Firebase health
        firebase_health = False
        try:
            from backend.firebase_client import is_firebase_available
            firebase_health = is_firebase_available()
        except Exception as e:
            logger.debug(f"Firebase health check unavailable: {e}")
        
        # Overall health status
        health_status = 'healthy'
        issues = []
        
        # Check for potential issues
        if memory_percent > HIGH_MEMORY_THRESHOLD:
            issues.append(f"High memory usage: {memory_percent:.1f}% (threshold: {HIGH_MEMORY_THRESHOLD}%)")
            
        if cpu_percent > HIGH_CPU_THRESHOLD:
            issues.append(f"High CPU usage: {cpu_percent:.1f}% (threshold: {HIGH_CPU_THRESHOLD}%)")
            
        if db_stats.get('utilization_percent', 0) > HIGH_DB_POOL_THRESHOLD:
            issues.append(f"High DB connection pool usage: {db_stats['utilization_percent']:.1f}% (threshold: {HIGH_DB_POOL_THRESHOLD}%)")
            
        if thread_count > HIGH_THREAD_THRESHOLD:
            issues.append(f"High thread count: {thread_count} (threshold: {HIGH_THREAD_THRESHOLD})")
            
        if issues:
            health_status = 'degraded'
            
        # Log warnings for issues
        for issue in issues:
            logger.warning(f"Health issue detected: {issue}")
        
        # Prepare circuit breaker status
        circuit_breaker_status = {}
        for service, state in circuit_breaker_states.items():
            circuit_breaker_status[service] = {
                'status': 'OPEN' if state['open'] else ('HALF_OPEN' if state['half_open'] else 'CLOSED'),
                'failures': state['failures'],
                'last_failure': datetime.fromtimestamp(state['last_failure_time']).isoformat() if state['last_failure_time'] else None
            }
        
        return {
            'status': health_status,
            'issues': issues,
            'timestamp': datetime.utcnow().isoformat(),
            'components': {
                'database': {
                    'status': 'healthy' if db_health else 'unhealthy',
                    'pool_stats': db_stats
                },
                'scheduler': {
                    'status': 'healthy' if scheduler_health else 'unhealthy',
                    'stats': scheduler_stats
                },
                'firebase': {
                    'status': 'healthy' if firebase_health else 'unhealthy'
                },
                'system': {
                    'memory_mb': memory_info.rss / 1024 / 1024,
                    'memory_percent': memory_percent,
                    'cpu_percent': cpu_percent,
                    'thread_count': thread_count,
                    'file_descriptors': fd_count,
                    'garbage_collector': {
                        'collections': sum(stat['collections'] for stat in gc_stats),
                        'collected': sum(stat['collected'] for stat in gc_stats)
                    }
                },
                'circuit_breakers': circuit_breaker_status
            },
            'configuration': {
                'thresholds': {
                    'memory': f"{HIGH_MEMORY_THRESHOLD}%",
                    'cpu': f"{HIGH_CPU_THRESHOLD}%",
                    'db_pool': f"{HIGH_DB_POOL_THRESHOLD}%",
                    'threads': HIGH_THREAD_THRESHOLD
                },
                'monitoring_interval': f"{RESOURCE_MONITORING_INTERVAL} seconds",
                'circuit_breaker_enabled': CIRCUIT_BREAKER_ENABLED,
                'circuit_breaker_threshold': CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                'circuit_breaker_timeout': f"{CIRCUIT_BREAKER_TIMEOUT} seconds"
            }
        }
    except Exception as e:
        logger.error(f"System health check failed: {e}", exc_info=True)
        return {
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }, 500

@app.route('/api/circuit-breaker-status')
def circuit_breaker_status():
    """Get current status of all circuit breakers."""
    try:
        status_report = {}
        for service, state in circuit_breaker_states.items():
            status_report[service] = {
                'status': 'OPEN' if state['open'] else ('HALF_OPEN' if state['half_open'] else 'CLOSED'),
                'failures': state['failures'],
                'last_failure_time': datetime.fromtimestamp(state['last_failure_time']).isoformat() if state['last_failure_time'] else None,
                'can_attempt_request': not state['open'] or (time.time() - state['last_failure_time'] > CIRCUIT_BREAKER_TIMEOUT if state['last_failure_time'] else False)
            }
        
        return {
            'circuit_breakers': status_report,
            'global_config': {
                'enabled': CIRCUIT_BREAKER_ENABLED,
                'failure_threshold': CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                'timeout_seconds': CIRCUIT_BREAKER_TIMEOUT,
                'monitored_services': critical_services
            },
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get circuit breaker status: {e}")
        return {'error': str(e)}, 500

@app.route('/api/reset-circuit-breaker/<service_name>', methods=['POST'])
@auth_required()
def reset_circuit_breaker(service_name):
    """Reset a specific circuit breaker (admin only)."""
    try:
        # Check if user is admin
        if not current_user.has_role('admin'):
            return {'error': 'Admin access required'}, 403
            
        if service_name in circuit_breaker_states:
            circuit_breaker_states[service_name].update({
                'failures': 0,
                'last_failure_time': None,
                'open': False,
                'half_open': False
            })
            logger.info(f"✅ Circuit breaker for {service_name} manually reset by admin {current_user.email}")
            return {'message': f'Circuit breaker for {service_name} reset successfully'}
        else:
            return {'error': f'Service {service_name} not found'}, 404
    except Exception as e:
        logger.error(f"Failed to reset circuit breaker: {e}")
        return {'error': str(e)}, 500

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


def cleanup_logging():
    """Clean up logging handlers gracefully."""
    logger.info("Shutting down logging system...")
    
    # Stop system monitoring
    try:
        stop_system_monitoring()
        logger.info("System monitoring stopped")
    except Exception as e:
        logger.error(f"Error stopping system monitoring: {e}")
    
    # Close all handlers
    for handler in logging.root.handlers[:]:
        try:
            handler.close()
            logging.root.removeHandler(handler)
            logger.info(f"Closed handler: {handler}")
        except Exception as e:
            logger.error(f"Error closing handler {handler}: {e}")
    
    logger.info("Logging system shut down complete")

# Resource monitoring and circuit breaker
resource_monitor_thread = None

# Global circuit breaker states for different services
circuit_breaker_states = {}  # Will store {service_name: {failures, last_failure_time, open, half_open}}

# Critical services that should use circuit breaker protection
critical_services = [
    'database',
    'firebase',
    'scheduler',
    'storage',
    'external_api'
]

def monitor_resources():
    """Monitor system resources and log warnings when thresholds are exceeded."""
    try:
        import psutil
        process = psutil.Process()
        
        # Track previous states to avoid repeated alerts
        last_alert_states = {
            'memory': False,
            'cpu': False,
            'threads': False,
            'db_pool': False
        }
        
        while True:
            try:
                current_states = {}
                alerts_triggered = []
                
                # Memory usage
                memory_percent = process.memory_percent()
                current_states['memory'] = memory_percent > HIGH_MEMORY_THRESHOLD
                if current_states['memory'] and not last_alert_states['memory']:
                    logger.info(f"High memory usage detected: {memory_percent:.1f}% (threshold: {HIGH_MEMORY_THRESHOLD}%)")
                    alerts_triggered.append(f"Memory: {memory_percent:.1f}%")
                
                # CPU usage
                cpu_percent = process.cpu_percent(interval=1)
                current_states['cpu'] = cpu_percent > HIGH_CPU_THRESHOLD
                if current_states['cpu'] and not last_alert_states['cpu']:
                    logger.info(f"High CPU usage detected: {cpu_percent:.1f}% (threshold: {HIGH_CPU_THRESHOLD}%)")
                    alerts_triggered.append(f"CPU: {cpu_percent:.1f}%")
                
                # Thread count
                thread_count = process.num_threads()
                current_states['threads'] = thread_count > HIGH_THREAD_THRESHOLD
                if current_states['threads'] and not last_alert_states['threads']:
                    logger.info(f"High thread count detected: {thread_count} (threshold: {HIGH_THREAD_THRESHOLD})")
                    alerts_triggered.append(f"Threads: {thread_count}")
                
                # Database connection pool (if available)
                try:
                    if hasattr(db, 'get_pool_stats'):
                        pool_stats = db.get_pool_stats()
                        pool_utilization = pool_stats.get('utilization_percent', 0)
                        current_states['db_pool'] = pool_utilization > HIGH_DB_POOL_THRESHOLD
                        if current_states['db_pool'] and not last_alert_states['db_pool']:
                            logger.warning(f"🚨 RESOURCE ALERT: High database pool utilization: {pool_utilization:.1f}% (threshold: {HIGH_DB_POOL_THRESHOLD}%)", extra={'alert_type': 'db_pool'})
                            alerts_triggered.append(f"DB Pool: {pool_utilization:.1f}%")
                except Exception as e:
                    logger.debug(f"Could not check DB pool stats: {e}")
                    current_states['db_pool'] = False
                
                # Log consolidated alert if multiple issues detected
                if alerts_triggered:
                    logger.warning(f"Multiple resource alerts detected: {', '.join(alerts_triggered)}")
                    
                    # Trigger circuit breaker if severe resource pressure
                    if len(alerts_triggered) >= 2:
                        logger.info("Severe resource pressure detected - circuit breaker monitoring active")
                        # This would trigger circuit breaker for critical services
                        
                # Update last states
                last_alert_states = current_states
                
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
            
            time.sleep(RESOURCE_MONITORING_INTERVAL)
            
    except ImportError:
        logger.info("psutil not available, resource monitoring disabled")
    except Exception as e:
        logger.error(f"Resource monitoring failed: {e}")

def start_resource_monitoring():
    """Start the resource monitoring thread - only once per process."""
    global resource_monitor_thread
    # Only start if not already running and we're in the main process
    # Protect against multiple workers in Gunicorn/uwsgi
    is_main_process = (os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or 
                      os.environ.get('ENABLE_SCHEDULER') == 'true')
    
    if (resource_monitor_thread is None or not resource_monitor_thread.is_alive()) and is_main_process:
        resource_monitor_thread = threading.Thread(target=monitor_resources, daemon=True)
        resource_monitor_thread.start()
        logger.info("Resource monitoring started in main process")
    elif not is_main_process:
        logger.info("Resource monitoring skipped - not in main process or scheduler disabled")

def circuit_breaker_call(service_name, func, *args, **kwargs):
    """Wrapper for circuit breaker pattern with service-specific tracking."""
    if not CIRCUIT_BREAKER_ENABLED:
        return func(*args, **kwargs)
    
    # Get or create service-specific circuit breaker state
    if service_name not in circuit_breaker_states:
        circuit_breaker_states[service_name] = {
            'failures': 0,
            'last_failure_time': None,
            'open': False,
            'half_open': False
        }
    
    cb_state = circuit_breaker_states[service_name]
    
    # Check if circuit breaker is open
    if cb_state['open']:
        if time.time() - cb_state['last_failure_time'] > CIRCUIT_BREAKER_TIMEOUT:
            # Half-open state - try one request
            logger.info(f"Circuit breaker for {service_name} in half-open state, testing...")
            cb_state['half_open'] = True
            cb_state['open'] = False
        else:
            logger.warning(f"Circuit breaker for {service_name} is OPEN - service temporarily unavailable")
            raise Exception(f"Circuit breaker is OPEN for {service_name} - service temporarily unavailable")
    
    try:
        result = func(*args, **kwargs)
        # Reset failure count on success
        cb_state['failures'] = 0
        cb_state['half_open'] = False
        logger.debug(f"Successful call to {service_name}, circuit breaker reset")
        return result
    except Exception as e:
        cb_state['failures'] += 1
        cb_state['last_failure_time'] = time.time()
        
        if cb_state['failures'] >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            cb_state['open'] = True
            cb_state['half_open'] = False
            logger.error(f"💥 Circuit breaker OPENED for {service_name} after {cb_state['failures']} failures: {str(e)}")
            # Send alert notification
            logger.critical(f"🚨 SERVICE FAILURE: {service_name} circuit breaker activated due to repeated failures", extra={'alert_type': 'service_failure', 'service': service_name})
        elif cb_state['failures'] >= CIRCUIT_BREAKER_FAILURE_THRESHOLD // 2:
            logger.warning(f"⚠️  Circuit breaker WARNING for {service_name}: {cb_state['failures']} failures detected")
        
        raise e

def record_health_metrics():
    """Record periodic health metrics for monitoring."""
    try:
        import psutil
        process = psutil.Process()
        
        # Record metrics
        memory_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent()
        thread_count = process.num_threads()
        
        # Database metrics
        db_stats = {}
        if hasattr(db, 'get_pool_stats'):
            db_stats = db.get_pool_stats()
        
        logger.info(f"HEALTH_METRICS - Memory: {memory_mb:.1f}MB, CPU: {cpu_percent:.1f}%, Threads: {thread_count}, DB_Pool: {db_stats.get('utilization_percent', 0):.1f}%")
        
    except Exception as e:
        logger.debug(f"Could not record health metrics: {e}")

def health_metrics_worker():
    """Worker thread for recording health metrics."""
    while True:
        try:
            record_health_metrics()
            time.sleep(300)  # Record every 5 minutes
        except Exception as e:
            logger.error(f"Health metrics worker error: {e}")
            time.sleep(60)  # Back off on error

if __name__ == '__main__':
    import atexit
    
    host = app.config.get('FLASK_HOST', '0.0.0.0')
    port = app.config.get('FLASK_PORT', 5000)
    debug = app.config.get('DEBUG', True)
    
    # Register cleanup function
    atexit.register(cleanup_logging)
    
    # Start resource monitoring - only if explicitly enabled or in main process
    if os.environ.get('ENABLE_SCHEDULER') == 'true' or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        start_resource_monitoring()
    else:
        logger.info("Background services disabled - set ENABLE_SCHEDULER=true to enable")
    
    # Start health metrics worker
    metrics_thread = threading.Thread(target=health_metrics_worker, daemon=True)
    metrics_thread.start()
    
    logger.info(f"Starting Flask app on {host}:{port} (debug={debug})")
    logger.info("Resource monitoring and health metrics enabled")
    
    try:
        app.run(host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
    finally:
        cleanup_logging()

   
