import logging

try:
    from firebase_admin import messaging
    from backend.firebase_client import initialize_firebase

    firebase_result = initialize_firebase()
    FIREBASE_AVAILABLE = bool(firebase_result) if firebase_result is not None else False
    if FIREBASE_AVAILABLE:
        logging.info("Firebase features enabled")
    else:
        logging.info("Firebase features disabled - mobile notifications unavailable")
except ImportError as e:
    logging.warning(f"Firebase not available: {e}")
    FIREBASE_AVAILABLE = False
    messaging = None


class PushNotificationService:
    @staticmethod
    def send(token, title, body, data=None) -> bool:
        if not FIREBASE_AVAILABLE:
            logging.warning("Firebase not available, skipping notification")
            return False

        print(token, title, body, data)
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=token,
            data=data or {}
        )
        try:
            response = messaging.send(message)
            logging.info(f"FCM Notification sent: {response}")
            return True
        except Exception as e:
            logging.error(f"Error sending notification: {e}", exc_info=True)
            return False
