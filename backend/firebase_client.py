import os
import logging
import atexit
from typing import Optional

logger = logging.getLogger(__name__)
_firebase_initialized = False
_firebase_app = None


def initialize_firebase() -> bool:
    """Initialize Firebase with proper lifecycle management and error handling."""
    global _firebase_initialized, _firebase_app
    
    # Return early if already initialized
    if _firebase_initialized and _firebase_app:
        logger.debug("Firebase already initialized, returning existing instance")
        return True
    
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.warning("Firebase dependencies not installed. Mobile app features will be disabled.")
        logger.warning("To enable Firebase, install with: pip install -r requirements-firebase.txt")
        return False
    
    # Check if Firebase is already initialized globally
    if firebase_admin._apps:
        logger.info("Firebase already initialized globally")
        _firebase_initialized = True
        _firebase_app = firebase_admin.get_app()
        return True
    
    # Validate required environment variables
    private_key = os.getenv("FIREBASE_PRIVATE_KEY")
    if not private_key:
        logger.warning("FIREBASE_PRIVATE_KEY environment variable not set. Firebase features disabled.")
        return False
    
    try:
        # Build credential dictionary
        cred_dict = {
            "type": os.getenv("FIREBASE_TYPE", "service_account"),
            "project_id": os.getenv("FIREBASE_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": private_key,
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
            "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_CERT_URL"),
            "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL"),
            "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN")
        }
        
        # Validate required fields
        required_fields = ["project_id", "private_key", "client_email"]
        missing_fields = [field for field in required_fields if not cred_dict.get(field)]
        if missing_fields:
            logger.error(f"Missing required Firebase configuration fields: {missing_fields}")
            return False
        
        # Initialize Firebase app
        cred = credentials.Certificate(cred_dict)
        _firebase_app = firebase_admin.initialize_app(cred, name="fleetwise-app")
        _firebase_initialized = True
        
        logger.info("Firebase initialized successfully")
        
        # Register cleanup function
        atexit.register(cleanup_firebase)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        _firebase_initialized = False
        _firebase_app = None
        return False


def cleanup_firebase() -> None:
    """Clean up Firebase resources gracefully."""
    global _firebase_initialized, _firebase_app
    
    if not _firebase_initialized or not _firebase_app:
        return
    
    try:
        import firebase_admin
        
        if firebase_admin._apps:
            logger.info("Cleaning up Firebase resources...")
            firebase_admin.delete_app(_firebase_app)
            logger.info("Firebase app deleted successfully")
        
        _firebase_initialized = False
        _firebase_app = None
        
    except Exception as e:
        logger.error(f"Error during Firebase cleanup: {e}")


def is_firebase_available() -> bool:
    """Check if Firebase is properly initialized and available."""
    global _firebase_initialized, _firebase_app
    
    if not _firebase_initialized or not _firebase_app:
        return False
    
    try:
        import firebase_admin
        return bool(firebase_admin._apps)
    except ImportError:
        return False


def get_firebase_app():
    """Get the Firebase app instance if available."""
    global _firebase_app
    return _firebase_app if _firebase_initialized else None

