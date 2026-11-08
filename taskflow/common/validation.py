"""Small input validation helpers used by the services."""
import re

from common.errors import ValidationError

# local-part@domain.tld — intentionally simple, but requires a dotted domain.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def require_text(value, field, max_length=200):
    """Return ``value`` stripped; reject empty or overly long text."""
    if value is None:
        raise ValidationError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field} must not be empty")
    if len(text) > max_length:
        raise ValidationError(f"{field} must be at most {max_length} characters")
    return text


def normalize_email(email):
    """Lower-case and validate an email address."""
    email = require_text(email, "email", max_length=254).lower()
    if not EMAIL_PATTERN.match(email):
        raise ValidationError(f"invalid email address: {email}")
    return email
