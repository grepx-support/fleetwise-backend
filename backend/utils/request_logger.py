"""
Enhanced request logging with detailed metrics and performance tracking
"""
import time
import logging
import json
from datetime import datetime
from typing import Dict, Any
from flask import request, g
import psutil

logger = logging.getLogger(__name__)

class RequestLogger:
    """Enhanced request logging with performance metrics"""
    
    @staticmethod
    def before_request():
        """Record request start time and initial metrics"""
        g.start_time = time.time()
        g.request_id = f"{int(time.time() * 1000000)}"  # Microsecond precision
        
        # Collect initial system state
        try:
            process = psutil.Process()
            g.initial_memory = process.memory_info().rss
            g.initial_cpu_times = process.cpu_times()
        except Exception as e:
            logger.debug(f"Could not collect initial process metrics: {e}")
            g.initial_memory = 0
            g.initial_cpu_times = None
    
    @staticmethod
    def after_request(response):
        """Log detailed request information with performance metrics"""
        if not hasattr(g, 'start_time'):
            return response
            
        # Calculate timing
        duration_ms = (time.time() - g.start_time) * 1000
        
        # Collect final system metrics
        memory_diff = 0
        cpu_user_time = 0
        cpu_system_time = 0
        
        try:
            if hasattr(g, 'initial_memory') and g.initial_memory > 0:
                process = psutil.Process()
                final_memory = process.memory_info().rss
                memory_diff = final_memory - g.initial_memory
                
                if hasattr(g, 'initial_cpu_times') and g.initial_cpu_times:
                    final_cpu_times = process.cpu_times()
                    cpu_user_time = final_cpu_times.user - g.initial_cpu_times.user
                    cpu_system_time = final_cpu_times.system - g.initial_cpu_times.system
        except Exception as e:
            logger.debug(f"Could not collect final process metrics: {e}")
        
        # Build request log data
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'request_id': getattr(g, 'request_id', 'unknown'),
            'method': request.method,
            'url': request.url,
            'endpoint': request.endpoint,
            'path': request.path,
            'remote_addr': request.remote_addr,
            'user_agent': str(request.user_agent),
            'content_length': request.content_length,
            'content_type': request.content_type,
            'duration_ms': round(duration_ms, 2),
            'status_code': response.status_code,
            'response_size': len(response.get_data()),
            'memory_delta_mb': round(memory_diff / (1024 * 1024), 3) if memory_diff > 0 else 0,
            'cpu_user_time': round(cpu_user_time, 4),
            'cpu_system_time': round(cpu_system_time, 4),
            'headers': dict(request.headers) if request.headers else {}
        }
        
        # Add query parameters for GET requests
        if request.args:
            log_data['query_params'] = dict(request.args)
        
        # Add JSON body for POST/PUT requests (if small enough)
        if request.is_json and request.content_length and request.content_length < 1024:
            try:
                log_data['json_body'] = request.get_json(silent=True)
            except Exception:
                pass
        
        # Log based on status code
        log_level = logging.INFO
        if response.status_code >= 500:
            log_level = logging.ERROR
        elif response.status_code >= 400:
            log_level = logging.WARNING
            
        logger.log(log_level, f"REQUEST_LOG: {json.dumps(log_data)}")
        
        return response

# Convenience functions
def log_slow_request(threshold_ms: float = 1000):
    """Decorator or function to log slow requests"""
    def decorator(f):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = f(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            
            if duration_ms > threshold_ms:
                logger.warning(f"SLOW_REQUEST: {request.method} {request.url} took {duration_ms:.2f}ms")
            
            return result
        return wrapper
    return decorator

def get_request_metrics() -> Dict[str, Any]:
    """Get current request metrics"""
    if not hasattr(g, 'start_time'):
        return {}
        
    duration_ms = (time.time() - g.start_time) * 1000
    
    return {
        'request_duration_ms': round(duration_ms, 2),
        'request_id': getattr(g, 'request_id', 'unknown'),
        'start_time': g.start_time
    }