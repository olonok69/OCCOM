# services/utils.py
from datetime import datetime
import re


def iso_utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing or replacing special characters.
    Keeps only alphanumeric characters, underscores, hyphens, and dots.

    Args:
        filename: Original filename to sanitize

    Returns:
        Sanitized filename safe for storage
    """
    # Split filename and extension (everything after last '.' is extension)
    name_parts = filename.rsplit(".", 1)
    name = name_parts[0]
    extension = name_parts[1]

    # Remove special characters, keep only alphanumeric, spaces, underscores, and hyphens
    name = re.sub(r"[^a-zA-Z0-9 _-]", "", name)

    # Remove leading/trailing spaces, underscores or hyphens
    name = name.strip(" _-")

    # Reconstruct filename with extension
    return f"{name}.{extension}"
