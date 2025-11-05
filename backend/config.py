import os
from pathlib import Path

# Set database configuration directly in code
os.environ['DB_TYPE'] = 'sqlite'
# Point to sibling fleetwise-storage/database directory
# Path structure: repos/fleetwise-backend/backend/config.py -> repos/fleetwise-storage/database
fleetwise_storage_path = str(Path(__file__).resolve().parents[2] / "fleetwise-storage" / "database")
os.environ['DB_PATH'] = os.path.join(fleetwise_storage_path, 'fleetwise.db')

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECURITY_PASSWORD_SALT = os.environ.get('SECURITY_PASSWORD_SALT', 'dev-salt')
    SECURITY_REGISTERABLE = True
    SECURITY_SEND_REGISTER_EMAIL = False
    SECURITY_PASSWORD_HASH = 'pbkdf2_sha512'
    SECURITY_TOKEN_AUTHENTICATION_HEADER = 'Authentication-Token'
    SECURITY_TOKEN_AUTHENTICATION_KEY = 'auth_token'
    SECURITY_RECOVERABLE = True
    SECURITY_CHANGEABLE = True
    SECURITY_CONFIRMABLE = False
    SECURITY_TRACKABLE = True
    SECURITY_LOGIN_WITHOUT_CONFIRMATION = True
    SECURITY_API_ENABLED = True
    SECURITY_URL_PREFIX = "/api/auth"
    WTF_CSRF_ENABLED = False
    SECURITY_CSRF_PROTECT_MECHANISMS = []
    SECURITY_CSRF_IGNORE_UNAUTH_ENDPOINTS = True
    SESSION_COOKIE_HTTPONLY = True
    SECURITY_UNAUTHORIZED_VIEW = None
    # REMEMBER_COOKIE_SAMESITE = "Strict"
    # REMEMBER_COOKIE_SECURE = True
    # REMEMBER_COOKIE_HTTPONLY = True
    
    # JSON API configurations
    SECURITY_RENDER_AS_JSON = True
    SECURITY_JSON = True
    SECURITY_JSON_ERRORS = True
    SECURITY_JSON_RESPONSE = True
        
    # File upload configurations
    MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 10 * 1024 * 1024))  # 10MB default
    MAX_ROWS_PER_FILE = int(os.environ.get('MAX_ROWS_PER_FILE', 1000))  # 1000 rows default
    ALLOWED_FILE_EXTENSIONS = {'.xlsx', '.xls'}

    # Email configuration for password reset
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@fleetwise.com')
    
    # Password reset configuration
    PASSWORD_RESET_TOKEN_EXPIRY_HOURS = int(os.environ.get('PASSWORD_RESET_TOKEN_EXPIRY_HOURS', 1))
    FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')


     # Upload folder for job photos
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    print("basedir ", BASE_DIR)
    JOB_PHOTO_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    STATIC_FOLDER = os.environ.get('STATIC_FOLDER', 'uploads')  # base static folder

    # invoice storage backup
    INVOICE_STORAGE_ROOT = os.getenv(
    "INVOICE_STORAGE_ROOT",
    str(Path(__file__).resolve().parents[2] / "fleetwise-storage")
)
 
class DevConfig(Config):
    SESSION_COOKIE_SAMESITE = 'Lax'  # Use Lax for development
    SESSION_COOKIE_SECURE = False
    # Development: Use 0.0.0.0 for cross-platform compatibility (Windows/Mac/Linux)
    FLASK_HOST = '0.0.0.0'
    FLASK_PORT = 5000
    FRONTEND_URL = 'http://localhost:3000'
    DEBUG = True

    def __init__(self):
        """Initialize DevConfig with database configuration from environment.

        Attempts to use DBManager for database configuration. If unavailable,
        gracefully falls back to a default SQLite URI to ensure application
        startup doesn't fail due to missing dependencies.
        """
        try:
            # Try to import DBManager from backend or local context
            try:
                from backend.database import DBManager
            except ImportError:
                from database import DBManager

            # Get database configuration from DBManager (single source of truth)
            self.SQLALCHEMY_DATABASE_URI = DBManager.get_sqlalchemy_uri()

            # For SQLite, also set DB_PATH for backwards compatibility
            db_instance = DBManager()
            if db_instance.is_sqlite():
                self.DB_PATH = db_instance.get_db_path()
                # Create directory if it doesn't exist
                db_dir = os.path.dirname(self.DB_PATH)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                    print(f"Created database directory: {db_dir}")
                print(f"Database path: {self.DB_PATH}")
                print(f"SQLAlchemy URI: {self.SQLALCHEMY_DATABASE_URI}")

        except Exception as e:
            # Graceful fallback if DBManager or database module is unavailable
            print(f"WARNING: DBManager unavailable ({e}), using fallback SQLite URI")
            # Path: backend/config.py -> repos/fleetwise-storage/database
            fallback_path = str(Path(__file__).resolve().parents[2] / "fleetwise-storage" / "database" / "fleetwise.db")
            self.SQLALCHEMY_DATABASE_URI = f"sqlite:///{fallback_path}"
            self.DB_PATH = fallback_path
            print(f"Fallback database path: {self.DB_PATH}")

class StagingConfig(Config):
    SESSION_COOKIE_SAMESITE = 'None'
    SESSION_COOKIE_SECURE = True
    # Staging: Use IPv6 dual-stack on Linux server
    FLASK_HOST = '::'
    FLASK_PORT = 5000
    FRONTEND_URL = 'https://test.grepx.sg'

class ProductionConfig(Config):
    SESSION_COOKIE_SAMESITE = 'None'
    SESSION_COOKIE_SECURE = True
    # Staging: Use IPv6 dual-stack on Linux server
    FLASK_HOST = '::'
    FLASK_PORT = 5000
    FRONTEND_URL = 'https://fleet.avant-garde.com.sg'

