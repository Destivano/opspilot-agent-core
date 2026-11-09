"""Small shared types; no AWS clients are created at import time."""

import hashlib
import json
import re
from datetime import datetime, timezone


class Problem(Exception):
    def __init__(self, status, detail, code=400):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


class Conflict(Exception):
    """An optimistic write lost to another request."""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def text_field(data, name, maximum=2000, pattern=None):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Problem("validation_error", f"{name} must be a non-empty string (max {maximum}).")
    value = value.strip()
    if pattern and not re.fullmatch(pattern, value):
        raise Problem("validation_error", f"{name} has an invalid format.")
    return value


def public_view(item):
    private = {"messages", "payload_hash", "version", "lease_until", "lease_id"}
    return {key: value for key, value in item.items() if key not in private}
