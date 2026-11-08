import re


def normalize_uuid(value: str, field: str) -> str:
    """Match the API's hyphenated UUID syntax without accepting alternate forms."""
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
    ):
        raise ValueError(f"{field} must be a UUID")
    return value.lower()
