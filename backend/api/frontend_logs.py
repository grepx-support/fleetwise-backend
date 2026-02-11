"""
API endpoint for receiving frontend logs
"""
from flask import Blueprint, request, jsonify
import logging
from datetime import datetime
import json

frontend_logs_bp = Blueprint('frontend_logs', __name__)
logger = logging.getLogger(__name__)

@frontend_logs_bp.route('/api/frontend-logs', methods=['POST'])
def receive_frontend_logs():
    """
    Receive frontend logs and process them
    """
    try:
        data = request.get_json()
        
        if not data or 'logs' not in data:
            return jsonify({'error': 'Invalid log data'}), 400
        
        logs = data['logs']
        client_timestamp = data.get('clientTimestamp')
        
        # Process each log entry
        processed_count = 0
        for log_entry in logs:
            try:
                # Add server-side timestamp
                log_entry['server_received_at'] = datetime.utcnow().isoformat()
                log_entry['client_sent_at'] = client_timestamp
                
                # Determine log level
                level = log_entry.get('level', 'INFO').upper()
                message = log_entry.get('message', 'Unknown message')
                log_data = log_entry.get('data', {})
                
                # Format for logging
                log_message = f"FRONTEND_{level}: {message}"
                if log_data:
                    log_message += f" | Data: {json.dumps(log_data, default=str)}"
                
                # Log based on level
                if level == 'ERROR':
                    logger.error(log_message)
                elif level == 'WARN':
                    logger.warning(log_message)
                elif level == 'DEBUG':
                    logger.debug(log_message)
                else:
                    logger.info(log_message)
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing frontend log entry: {e}")
                continue
        
        logger.info(f"Processed {processed_count}/{len(logs)} frontend log entries")
        
        return jsonify({
            'success': True,
            'processed': processed_count,
            'total': len(logs)
        }), 200
        
    except Exception as e:
        logger.error(f"Error receiving frontend logs: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@frontend_logs_bp.route('/api/frontend-logs/batch', methods=['POST'])
def receive_batch_frontend_logs():
    """
    Receive batch of frontend logs with metadata
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Extract batch information
        batch_id = data.get('batchId', 'unknown')
        session_id = data.get('sessionId')
        user_id = data.get('userId')
        logs = data.get('logs', [])
        
        logger.info(f"Received frontend log batch {batch_id} with {len(logs)} entries")
        
        # Process logs (same as single endpoint)
        processed_count = 0
        for log_entry in logs:
            try:
                log_entry.update({
                    'batch_id': batch_id,
                    'session_id': session_id,
                    'user_id': user_id,
                    'server_received_at': datetime.utcnow().isoformat()
                })
                
                level = log_entry.get('level', 'INFO').upper()
                message = log_entry.get('message', 'Batch log entry')
                log_data = log_entry.get('data', {})
                
                log_message = f"BATCH_FRONTEND_{level}: {message}"
                if log_data:
                    log_message += f" | Batch: {batch_id} | Data: {json.dumps(log_data, default=str)}"
                
                if level == 'ERROR':
                    logger.error(log_message)
                elif level == 'WARN':
                    logger.warning(log_message)
                elif level == 'DEBUG':
                    logger.debug(log_message)
                else:
                    logger.info(log_message)
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing batch log entry: {e}")
                continue
        
        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'processed': processed_count,
            'total': len(logs)
        }), 200
        
    except Exception as e:
        logger.error(f"Error receiving batch frontend logs: {e}")
        return jsonify({'error': 'Internal server error'}), 500