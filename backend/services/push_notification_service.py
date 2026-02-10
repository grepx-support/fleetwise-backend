import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    from firebase_admin import messaging
    from backend.firebase_client import initialize_firebase, is_firebase_available

    # Initialize Firebase
    firebase_result = initialize_firebase()
    FIREBASE_AVAILABLE = is_firebase_available()
    
    if FIREBASE_AVAILABLE:
        logger.info("Firebase features enabled for push notifications")
    else:
        logger.info("Firebase features disabled - mobile notifications unavailable")
except ImportError as e:
    logger.warning(f"Firebase not available: {e}")
    FIREBASE_AVAILABLE = False
    messaging = None


class PushNotificationService:
    @staticmethod
    def send(token: str, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """Send a push notification via Firebase Cloud Messaging."""
        if not FIREBASE_AVAILABLE:
            logger.warning("Firebase not available, skipping notification")
            return False
        
        if not token:
            logger.warning("No device token provided, skipping notification")
            return False
            
        if not title and not body:
            logger.warning("No title or body provided, skipping notification")
            return False

        try:
            # Prepare the message
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                token=token,
                data=data or {}
            )
            
            # Send the message
            response = messaging.send(message)
            logger.info(f"FCM Notification sent successfully: {response}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending notification to token {token[:10]}...: {e}", exc_info=True)
            return False
    
    @staticmethod
    def send_batch(tokens: list, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> dict:
        """Send notifications to multiple devices."""
        if not FIREBASE_AVAILABLE:
            logger.warning("Firebase not available, skipping batch notification")
            return {"success": 0, "failure": len(tokens)}
        
        if not tokens:
            logger.warning("No device tokens provided for batch notification")
            return {"success": 0, "failure": 0}
        
        success_count = 0
        failure_count = 0
        
        for token in tokens:
            if PushNotificationService.send(token, title, body, data):
                success_count += 1
            else:
                failure_count += 1
                
        logger.info(f"Batch notification completed: {success_count} success, {failure_count} failure")
        return {"success": success_count, "failure": failure_count}
    
    @staticmethod
    def is_available() -> bool:
        """Check if push notifications are available."""
        return FIREBASE_AVAILABLE
