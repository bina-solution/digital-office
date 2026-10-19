"""
Centralized logging configuration for apitools.

Features:
- Structured JSON logging for production
- Human-readable format for development
- Request context (request_id, client_ip, file_id)
- Automatic IP extraction from Traefik headers
- Performance logging for slow requests
"""

import logging
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from logging.handlers import RotatingFileHandler
from typing import Optional, Any
from contextvars import ContextVar

# Context variables for request tracking
request_context: ContextVar[dict] = ContextVar('request_context', default={})

# Configuration from environment
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FORMAT = os.getenv('LOG_FORMAT', 'json')  # 'json' or 'text'
DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
SLOW_REQUEST_THRESHOLD_MS = int(os.getenv('SLOW_REQUEST_THRESHOLD_MS', '5000'))


class RequestContextFilter(logging.Filter):
    """Injects request context into log records."""
    
    def filter(self, record):
        ctx = request_context.get()
        record.request_id = ctx.get('request_id', '-')
        record.client_ip = ctx.get('client_ip', '-')
        record.real_ip = ctx.get('real_ip', '-')
        record.file_id = ctx.get('file_id', '-')
        record.endpoint = ctx.get('endpoint', '-')
        record.method = ctx.get('method', '-')
        return True


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON for production use."""
    
    def format(self, record):
        log_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'request_id': getattr(record, 'request_id', '-'),
            'client_ip': getattr(record, 'client_ip', '-'),
            'real_ip': getattr(record, 'real_ip', '-'),
        }
        
        # Add optional fields if present
        if getattr(record, 'file_id', '-') != '-':
            log_data['file_id'] = record.file_id
        if getattr(record, 'endpoint', '-') != '-':
            log_data['endpoint'] = record.endpoint
        if getattr(record, 'method', '-') != '-':
            log_data['method'] = record.method
        if hasattr(record, 'duration_ms'):
            log_data['duration_ms'] = record.duration_ms
        if hasattr(record, 'status_code'):
            log_data['status_code'] = record.status_code
        if hasattr(record, 'user_agent'):
            log_data['user_agent'] = record.user_agent
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)
            
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
            
        return json.dumps(log_data, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable format for development."""
    
    def format(self, record):
        request_id = getattr(record, 'request_id', '-')
        real_ip = getattr(record, 'real_ip', '-')
        
        # Truncate request_id for readability
        short_id = request_id[:8] if request_id != '-' else '-'
        
        base = f"{self.formatTime(record)} {record.levelname:<7} [{short_id}] {real_ip:<15} {record.getMessage()}"
        
        if record.exc_info:
            base += f"\n{self.formatException(record.exc_info)}"
            
        return base


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger for the given module name."""
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if not logger.handlers:
        configure_logger(logger)
    
    return logger


def configure_logger(logger: logging.Logger):
    """Configure a logger with appropriate handlers."""
    logger.setLevel(getattr(logging, LOG_LEVEL))
    logger.propagate = False
    
    # Add context filter
    logger.addFilter(RequestContextFilter())
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, LOG_LEVEL))
    
    if LOG_FORMAT == 'json' and not DEBUG:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(TextFormatter(
            fmt='%(asctime)s %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
    
    logger.addHandler(console_handler)
    
    # File handler for production
    if not DEBUG:
        os.makedirs('logs', exist_ok=True)
        file_handler = RotatingFileHandler(
            'logs/apitools.log',
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=10
        )
        file_handler.setLevel(getattr(logging, LOG_LEVEL))
        file_handler.setFormatter(JSONFormatter())
        file_handler.addFilter(RequestContextFilter())
        logger.addHandler(file_handler)


def get_client_ip(request) -> tuple[str, str]:
    """
    Extract client IP from request, handling Traefik proxy headers.
    
    Returns:
        tuple: (direct_ip, real_ip) - direct_ip is from socket, real_ip is the actual client
    """
    direct_ip = request.remote_addr or '-'
    
    # Traefik sets X-Real-IP
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return direct_ip, real_ip
    
    # Fallback to X-Forwarded-For (first IP in chain)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        real_ip = forwarded_for.split(',')[0].strip()
        return direct_ip, real_ip
    
    return direct_ip, direct_ip


def set_request_context(
    request_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    real_ip: Optional[str] = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    file_id: Optional[str] = None,
    **kwargs
):
    """Set the current request context for logging."""
    ctx = request_context.get().copy()
    
    if request_id:
        ctx['request_id'] = request_id
    if client_ip:
        ctx['client_ip'] = client_ip
    if real_ip:
        ctx['real_ip'] = real_ip
    if endpoint:
        ctx['endpoint'] = endpoint
    if method:
        ctx['method'] = method
    if file_id:
        ctx['file_id'] = file_id
    
    ctx.update(kwargs)
    request_context.set(ctx)


def clear_request_context():
    """Clear the current request context."""
    request_context.set({})


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())[:8]


def log_request_start(logger: logging.Logger, request):
    """Log the start of a request with full context."""
    client_ip, real_ip = get_client_ip(request)
    request_id = generate_request_id()
    
    set_request_context(
        request_id=request_id,
        client_ip=client_ip,
        real_ip=real_ip,
        endpoint=request.path,
        method=request.method
    )
    
    logger.info(f"Request: {request.method} {request.path}",
                extra={'user_agent': request.headers.get('User-Agent', '-')})
    
    return request_id, time.time()


def log_request_end(logger: logging.Logger, status_code: int, start_time: float):
    """Log the end of a request with timing."""
    duration_ms = int((time.time() - start_time) * 1000)
    
    log_level = logging.INFO
    if status_code >= 500:
        log_level = logging.ERROR
    elif status_code >= 400:
        log_level = logging.WARNING
    elif duration_ms > SLOW_REQUEST_THRESHOLD_MS:
        log_level = logging.WARNING
    
    ctx = request_context.get()
    message = f"Response: {status_code} in {duration_ms}ms"
    
    if duration_ms > SLOW_REQUEST_THRESHOLD_MS:
        message = f"SLOW {message}"
    
    logger.log(log_level, message, extra={
        'status_code': status_code,
        'duration_ms': duration_ms
    })
    
    clear_request_context()


def log_with_context(logger: logging.Logger, level: int, message: str, **extra):
    """Log a message with additional context data."""
    logger.log(level, message, extra={'extra_data': extra})


# Create the main application logger
app_logger = get_logger('apitools')


# Convenience functions for common logging patterns
def log_ocr_request(file_id: str, operation: str):
    """Log OCR-related operations."""
    ctx = request_context.get()
    ctx['file_id'] = file_id
    request_context.set(ctx)
    app_logger.info(f"OCR {operation}", extra={'extra_data': {'file_id': file_id}})


def log_debug(message: str, **kwargs):
    """Log debug message with optional extra data."""
    if kwargs:
        app_logger.debug(message, extra={'extra_data': kwargs})
    else:
        app_logger.debug(message)


def log_info(message: str, **kwargs):
    """Log info message with optional extra data."""
    if kwargs:
        app_logger.info(message, extra={'extra_data': kwargs})
    else:
        app_logger.info(message)


def log_warning(message: str, **kwargs):
    """Log warning message with optional extra data."""
    if kwargs:
        app_logger.warning(message, extra={'extra_data': kwargs})
    else:
        app_logger.warning(message)


def log_error(message: str, exc_info=False, **kwargs):
    """Log error message with optional exception info."""
    if kwargs:
        app_logger.error(message, exc_info=exc_info, extra={'extra_data': kwargs})
    else:
        app_logger.error(message, exc_info=exc_info)
