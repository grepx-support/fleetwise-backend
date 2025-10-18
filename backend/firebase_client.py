import os
import logging

def initialize_firebase():
    """Initialize Firebase with error handling for missing dependencies"""
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logging.warning("Firebase dependencies not installed. Mobile app features will be disabled.")
        logging.warning("To enable Firebase, install with: pip install -r requirements-firebase.txt")
        return False
    
    if not firebase_admin._apps:
        private_key = os.getenv("FIREBASE_PRIVATE_KEY")
        if not private_key:
            logging.warning("FIREBASE_PRIVATE_KEY environment variable not set.")
            return False
        
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
        
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        logging.info("Firebase initialized successfully")
        return True
    
    return True

