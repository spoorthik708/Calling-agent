"""Utility functions for Phone Number Normalization, Validation, and CSV Import Parsing."""

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple


def normalize_phone_number(raw_phone: Optional[str]) -> Optional[str]:
    """
    Normalizes a raw phone number string to E.164 format.
    Strips non-numeric formatting characters. Accepts numbers with or without leading '+'.
    Returns None if the phone number is invalid (fewer than 7 digits or invalid characters).
    """
    if not raw_phone:
        return None

    cleaned = str(raw_phone).strip()
    if not cleaned:
        return None

    has_plus = cleaned.startswith("+")
    # Remove all non-digit characters except leading plus
    digits_only = re.sub(r"[^\d]", "", cleaned)

    if len(digits_only) < 7 or len(digits_only) > 15:
        return None

    if has_plus:
        return f"+{digits_only}"
    elif len(digits_only) == 10:
        # Default US/NANP 10-digit format
        return f"+1{digits_only}"
    else:
        return f"+{digits_only}"


def parse_contacts_csv(
    content_bytes: bytes,
    max_file_size_bytes: int = 10 * 1024 * 1024,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Parses a CSV file safely and extracts contact details.
    Enforces maximum file size, header recognition, phone normalization,
    and intra-file duplicate detection.

    Returns:
        (accepted_rows, rejected_rows, stats_dict)
    """
    if len(content_bytes) > max_file_size_bytes:
        raise ValueError(f"File size exceeds maximum threshold of {max_file_size_bytes // (1024 * 1024)}MB.")

    # Safe multi-encoding decode
    text_content = ""
    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            text_content = content_bytes.decode(encoding)
            break
        except (UnicodeDecodeError, AttributeError):
            continue

    if not text_content:
        raise ValueError("Unable to decode file content. Please ensure valid UTF-8 encoding.")

    # Read CSV
    stream = io.StringIO(text_content)
    reader = csv.reader(stream)

    try:
        raw_headers = next(reader)
    except StopIteration:
        raise ValueError("CSV file is empty.")

    # Identify header columns flexibly
    phone_col_idx = -1
    name_col_idx = -1
    email_col_idx = -1
    tags_col_idx = -1

    for idx, header in enumerate(raw_headers):
        h_clean = header.strip().lower().replace("_", "").replace(" ", "").replace("-", "")
        if h_clean in ["phone", "phonenumber", "mobile", "telephone", "cell", "number", "contactnumber"]:
            phone_col_idx = idx
        elif h_clean in ["name", "fullname", "contactname", "firstname", "displayname"]:
            name_col_idx = idx
        elif h_clean in ["email", "emailaddress", "mail"]:
            email_col_idx = idx
        elif h_clean in ["tag", "tags", "labels", "category"]:
            tags_col_idx = idx

    # Fallback: if no explicit phone header, check if first column contains phone numbers
    if phone_col_idx == -1:
        if len(raw_headers) > 0:
            phone_col_idx = 0
        else:
            raise ValueError("CSV file must contain a 'phone' or 'phone_number' column.")

    accepted_rows: List[Dict[str, Any]] = []
    rejected_rows: List[Dict[str, Any]] = []
    seen_phones_in_file: set = set()

    row_index = 1
    for row in reader:
        row_index += 1
        if not row or all(not str(cell).strip() for cell in row):
            continue

        raw_phone = row[phone_col_idx].strip() if phone_col_idx < len(row) else ""
        raw_name = row[name_col_idx].strip() if name_col_idx != -1 and name_col_idx < len(row) else ""
        raw_email = row[email_col_idx].strip() if email_col_idx != -1 and email_col_idx < len(row) else ""
        raw_tags = row[tags_col_idx].strip() if tags_col_idx != -1 and tags_col_idx < len(row) else ""

        normalized_phone = normalize_phone_number(raw_phone)
        if not normalized_phone:
            rejected_rows.append({
                "row_index": row_index,
                "raw_phone": raw_phone,
                "name": raw_name,
                "reason": f"Invalid or malformed phone number format ('{raw_phone}')",
            })
            continue

        if normalized_phone in seen_phones_in_file:
            rejected_rows.append({
                "row_index": row_index,
                "raw_phone": raw_phone,
                "normalized_phone": normalized_phone,
                "name": raw_name,
                "reason": f"Duplicate phone number within file ('{normalized_phone}')",
            })
            continue

        seen_phones_in_file.add(normalized_phone)

        # Parse tags
        tags_list = [t.strip() for t in re.split(r"[,;|]", raw_tags) if t.strip()]

        accepted_rows.append({
            "row_index": row_index,
            "name": raw_name,
            "phone_number": normalized_phone,
            "email": raw_email if "@" in raw_email else None,
            "tags": tags_list,
        })

    stats = {
        "total_rows": row_index - 1,
        "accepted_count": len(accepted_rows),
        "rejected_count": len(rejected_rows),
        "duplicate_count": sum(1 for r in rejected_rows if "Duplicate" in r["reason"]),
    }

    return accepted_rows, rejected_rows, stats
