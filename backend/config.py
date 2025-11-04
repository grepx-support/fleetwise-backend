import os
from pathlib import Path

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

    # Ensure consistent database path regardless of working directory
    DB_PATH = os.path.join(Config.BASE_DIR, 'app.db')
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
    DEBUG = True

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

