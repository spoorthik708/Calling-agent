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


def validate_tool_arguments(
    arguments: Dict[str, Any],
    max_bytes: int = 64 * 1024,
    max_string_len: int = 10000,
    max_array_len: int = 500,
    max_dict_keys: int = 100,
    max_depth: int = 10,
) -> None:
    """
    Validates arguments passed into any tool invocation before execution.
    Enforces strict bounded limits to prevent resource exhaustion and injection:
    - Overall JSON payload size <= max_bytes (default 64KB)
    - Recursion depth <= max_depth (default 10)
    - Individual string length <= max_string_len (default 10,000 chars)
    - Array size <= max_array_len (default 500 items)
    - Dict key count <= max_dict_keys (default 100 keys)
    - Null-byte rejection
    - Arbitrary code, shell, SQL, or local filesystem path injection rejection.
    """
    if not isinstance(arguments, dict):
        raise ToolExecutionSecurityError("Tool arguments must be provided as a dictionary/object.")

    import json
    try:
        serialized = json.dumps(arguments)
        if len(serialized.encode("utf-8")) > max_bytes:
            raise ToolExecutionSecurityError(
                f"Tool arguments payload size exceeds maximum limit of {max_bytes} bytes."
            )
    except (TypeError, ValueError) as json_err:
        raise ToolExecutionSecurityError(f"Tool arguments could not be safely serialized: {str(json_err)}")

    def check_value(val: Any, current_depth: int = 0) -> None:
        if current_depth > max_depth:
            raise ToolExecutionSecurityError(
                f"Tool arguments exceed maximum allowed nesting depth of {max_depth} levels."
            )

        if isinstance(val, str):
            if "\x00" in val:
                raise ToolExecutionSecurityError("Null bytes in tool arguments are strictly prohibited.")
            if len(val) > max_string_len:
                raise ToolExecutionSecurityError(
                    f"Tool argument string exceeds maximum length of {max_string_len} characters."
                )
            for pattern in DISALLOWED_PATTERNS:
                if pattern.search(val):
                    raise ToolExecutionSecurityError(
                        f"Security validation failed: Prohibited pattern detected in tool parameter: '{val[:40]}...'"
                    )
        elif isinstance(val, dict):
            if len(val) > max_dict_keys:
                raise ToolExecutionSecurityError(
                    f"Tool argument object exceeds maximum allowed key count of {max_dict_keys}."
                )
            for k, v in val.items():
                if not isinstance(k, str):
                    raise ToolExecutionSecurityError("Tool argument dictionary keys must be strings.")
                if "\x00" in k or len(k) > 256:
                    raise ToolExecutionSecurityError("Invalid tool argument key.")
                check_value(k, current_depth + 1)
                check_value(v, current_depth + 1)
        elif isinstance(val, list):
            if len(val) > max_array_len:
                raise ToolExecutionSecurityError(
                    f"Tool argument list exceeds maximum allowed item count of {max_array_len}."
                )
            for item in val:
                check_value(item, current_depth + 1)

    check_value(arguments, 0)


def sanitize_text_input(text: str, max_length: int = 10000) -> str:
    """Sanitizes user input string and enforces length bounds."""
    if not isinstance(text, str):
        return ""
    # Strip null bytes and normalize whitespace
    cleaned = text.replace("\x00", "").strip()
    return cleaned[:max_length]
