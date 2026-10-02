import json
import logging
import re
import sys
from typing import Any, Dict


# Regex patterns for sensitive field redaction
SENSITIVE_PATTERNS = [
    re.compile(r'"?(password|secret|token|api_key|authorization|bearer|card_number)"?\s*[:=]\s*"?[^",\s]+"?', re.IGNORECASE),
    re.compile(r'bearer\s+[a-zA-Z0-9_\-\.]+', re.IGNORECASE),
]

SENSITIVE_KEYS = {
    "password", "secret", "token", "access_token", "refresh_token",
    "api_key", "apikey", "authorization", "auth", "secret_key",
    "card_number", "cvv", "ssn", "credentials"
}


def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively scrub sensitive keys from dictionaries."""
    sanitized: Dict[str, Any] = {}
    for key, value in data.items():
        if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        elif isinstance(value, str):
            scrubbed = value
            for pattern in SENSITIVE_PATTERNS:
                scrubbed = pattern.sub(r'\1="[REDACTED]"', scrubbed)
            sanitized[key] = scrubbed
        else:
            sanitized[key] = value
    return sanitized


class JsonFormatter(logging.Formatter):
    """Formats log records as structured JSON without sensitive credentials."""
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if hasattr(record, "tenant_id"):
            log_obj["tenant_id"] = str(record.tenant_id)
        if hasattr(record, "request_id"):
            log_obj["request_id"] = str(record.request_id)
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Scrub sensitive data from log message and object
        sanitized = sanitize_dict(log_obj)
        return json.dumps(sanitized)


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configures structured, sanitized application logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s"))
    
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Returns a named logger."""
    return logging.getLogger(name)
