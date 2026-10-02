import re
from typing import Any, Dict, List
from app.core.exceptions import ToolExecutionSecurityError

# Patterns indicative of malicious execution attempts
DISALLOWED_PATTERNS = [
    re.compile(r"\b(eval|exec|compile|__import__|os\.system|subprocess|shutil)\b", re.IGNORECASE),
    re.compile(r"\b(rm\s+-rf|del\s+/f|format\s+[a-z]:|powershell|bash|sh|cmd\.exe)\b", re.IGNORECASE),
    re.compile(r"\b(drop\s+table|delete\s+from|insert\s+into|update\s+set|union\s+select)\b", re.IGNORECASE),
    re.compile(r"(file:\/\/|\/etc\/passwd|c:\\windows\\system32)", re.IGNORECASE),
]


def validate_tool_arguments(arguments: Dict[str, Any]) -> None:
    """
    Validates arguments passed into any tool invocation before execution.
    Explicitly blocks attempts to inject arbitrary python, shell, SQL, or local filesystem paths.
    """
    def check_value(val: Any) -> None:
        if isinstance(val, str):
            for pattern in DISALLOWED_PATTERNS:
                if pattern.search(val):
                    raise ToolExecutionSecurityError(
                        f"Security validation failed: Prohibited pattern detected in tool parameter: '{val[:40]}...'"
                    )
        elif isinstance(val, dict):
            for k, v in val.items():
                check_value(k)
                check_value(v)
        elif isinstance(val, list):
            for item in val:
                check_value(item)

    check_value(arguments)


def sanitize_text_input(text: str, max_length: int = 10000) -> str:
    """Sanitizes user input string and enforces length bounds."""
    if not isinstance(text, str):
        return ""
    # Strip null bytes and normalize whitespace
    cleaned = text.replace("\x00", "").strip()
    return cleaned[:max_length]
