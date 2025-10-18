from flask import Blueprint, request, jsonify
from services.fcm_service import send_push_notification

notification_bp = Blueprint('notifications', __name__)

@notification_bp.route('/notify', methods=['POST'])
def notify():
    data = request.json
    token = data.get('token')
    title = data.get('title')
    body = data.get('body')

    if not all([token, title, body]):
        return jsonify({'error': 'Missing token/title/body'}), 400

    success = send_push_notification(token, title, body)

    return jsonify({'message': 'Notification sent' if success else 'Failed'}), 200
