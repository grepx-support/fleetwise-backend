"""
Circuit Breaker Utility Module

Provides easy-to-use decorators and utilities for implementing circuit breaker patterns
in critical services throughout the application.
"""

import functools
import time
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Global circuit breaker states (imported from server.py)
try:
    from backend.server import circuit_breaker_states, CIRCUIT_BREAKER_ENABLED, \
                               CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_TIMEOUT
except ImportError:
    # Fallback configuration for standalone use
    circuit_breaker_states = {}
    CIRCUIT_BREAKER_ENABLED = True
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
    CIRCUIT_BREAKER_TIMEOUT = 60


class CircuitBreakerException(Exception):
    """Raised when circuit breaker prevents a call."""
    pass


def circuit_breaker(service_name: str, exception_types: tuple = (Exception,), fallback=None):
    """
    Decorator for applying circuit breaker pattern to functions.
    
    Args:
        service_name: Name of the service for tracking
        exception_types: Tuple of exception types that trigger circuit breaker
        fallback: Optional fallback function to call when circuit is open
    
    Usage:
        @circuit_breaker('database')
        def get_user_data(user_id):
            return db.query(User).filter(User.id == user_id).first()
            
        @circuit_breaker('external_api', fallback=lambda: {'status': 'offline'})
        def call_external_service():
            return requests.get('https://api.example.com/data').json()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
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
                    if fallback is not None:
                        logger.info(f"Using fallback for {service_name}")
                        return fallback()
                    raise CircuitBreakerException(f"Circuit breaker is OPEN for {service_name}")
            
            try:
                result = func(*args, **kwargs)
                # Reset failure count on success
                cb_state['failures'] = 0
                cb_state['half_open'] = False
                logger.debug(f"Successful call to {service_name}, circuit breaker reset")
                return result
            except exception_types as e:
                cb_state['failures'] += 1
                cb_state['last_failure_time'] = time.time()
                
                if cb_state['failures'] >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
                    cb_state['open'] = True
                    cb_state['half_open'] = False
                    logger.error(f"💥 Circuit breaker OPENED for {service_name} after {cb_state['failures']} failures: {str(e)}")
                    # Send alert notification
                    logger.critical(f"🚨 SERVICE FAILURE: {service_name} circuit breaker activated", 
                                  extra={'alert_type': 'service_failure', 'service': service_name})
                elif cb_state['failures'] >= CIRCUIT_BREAKER_FAILURE_THRESHOLD // 2:
                    logger.warning(f"⚠️  Circuit breaker WARNING for {service_name}: {cb_state['failures']} failures detected")
                
                # Re-raise the original exception
                raise e
            except Exception as e:
                # For non-monitored exceptions, still re-raise
                raise e
        
        return wrapper
    return decorator


def get_circuit_breaker_status(service_name: str) -> dict:
    """
    Get the current status of a specific circuit breaker.
    
    Args:
        service_name: Name of the service
        
    Returns:
        Dictionary with circuit breaker status information
    """
    if service_name not in circuit_breaker_states:
        return {
            'status': 'CLOSED',
            'failures': 0,
            'last_failure_time': None,
            'can_attempt_request': True
        }
    
    state = circuit_breaker_states[service_name]
    return {
        'status': 'OPEN' if state['open'] else ('HALF_OPEN' if state['half_open'] else 'CLOSED'),
        'failures': state['failures'],
        'last_failure_time': state['last_failure_time'],
        'can_attempt_request': not state['open'] or (
            time.time() - state['last_failure_time'] > CIRCUIT_BREAKER_TIMEOUT 
            if state['last_failure_time'] else False
        )
    }


def reset_circuit_breaker(service_name: str) -> bool:
    """
    Manually reset a circuit breaker.
    
    Args:
        service_name: Name of the service to reset
        
    Returns:
        True if reset successful, False if service not found
    """
    if service_name in circuit_breaker_states:
        circuit_breaker_states[service_name].update({
            'failures': 0,
            'last_failure_time': None,
            'open': False,
            'half_open': False
        })
        logger.info(f"✅ Circuit breaker for {service_name} manually reset")
        return True
    return False


def get_all_circuit_breaker_statuses() -> dict:
    """
    Get status of all circuit breakers.
    
    Returns:
        Dictionary mapping service names to their statuses
    """
    return {
        service: get_circuit_breaker_status(service)
        for service in circuit_breaker_states.keys()
    }


# Predefined circuit breaker decorators for common services

def database_circuit_breaker(func):
    """Circuit breaker for database operations."""
    return circuit_breaker('database')(func)


def firebase_circuit_breaker(func):
    """Circuit breaker for Firebase operations."""
    return circuit_breaker('firebase')(func)


def scheduler_circuit_breaker(func):
    """Circuit breaker for scheduler operations."""
    return circuit_breaker('scheduler')(func)


def storage_circuit_breaker(func):
    """Circuit breaker for storage operations."""
    return circuit_breaker('storage')(func)


def external_api_circuit_breaker(func):
    """Circuit breaker for external API calls."""
    return circuit_breaker('external_api')(func)


# Context manager for manual circuit breaker control
class CircuitBreakerContext:
    """
    Context manager for wrapping code blocks with circuit breaker protection.
    
    Usage:
        with CircuitBreakerContext('database') as cb:
            if cb.can_execute():
                result = perform_database_operation()
                cb.success()
                return result
            else:
                return handle_circuit_open()
    """
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.cb_state = None
        
    def __enter__(self):
        # Initialize circuit breaker state if needed
        if self.service_name not in circuit_breaker_states:
            circuit_breaker_states[self.service_name] = {
                'failures': 0,
                'last_failure_time': None,
                'open': False,
                'half_open': False
            }
        self.cb_state = circuit_breaker_states[self.service_name]
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # Handle exception
            if issubclass(exc_type, Exception):
                self.cb_state['failures'] += 1
                self.cb_state['last_failure_time'] = time.time()
                
                if self.cb_state['failures'] >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
                    self.cb_state['open'] = True
                    self.cb_state['half_open'] = False
                    logger.error(f"💥 Circuit breaker OPENED for {self.service_name} after {self.cb_state['failures']} failures: {str(exc_val)}")
                # Do not suppress the exception; allow it to propagate
                return False
        else:
            # Success case
            self.cb_state['failures'] = 0
            self.cb_state['half_open'] = False
            
    def can_execute(self) -> bool:
        """Check if operation can be attempted."""
        if self.cb_state['open']:
            if time.time() - self.cb_state['last_failure_time'] > CIRCUIT_BREAKER_TIMEOUT:
                # Half-open state
                self.cb_state['half_open'] = True
                self.cb_state['open'] = False
                return True
            return False
        return True
        
    def success(self):
        """Mark operation as successful."""
        self.cb_state['failures'] = 0
        self.cb_state['half_open'] = False