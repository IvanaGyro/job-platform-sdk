"""104 resumeTimestamp concurrency precondition, shared by SDK and HTTP.

The 104 editor exposes a resumeTimestamp in the native resume GET and a
separate 104-profile-ver transport header. Checking this timestamp does not
prove server-side atomic conflict control, but must never accept a missing
GET version or invalid caller-supplied precondition as equal.
"""
from __future__ import annotations

from typing import Any

from job_platforms.core.errors import ConflictError

# Accept both site-supplied integers and opaque nonempty string revisions.
# Strings like "None" are not revisions; Python's str(None) comparison was
# previously able to turn a missing GET timestamp into an apparent match.
_INVALID_STRINGS = frozenset(("none", "null", "undefined", "nan", "true", "false"))
MAX_REVISION_LENGTH = 128


def is_revision(value: Any) -> bool:
    if type(value) is int:
        return 0 <= value < 10 ** MAX_REVISION_LENGTH
    if type(value) is str:
        return (
            0 < len(value) <= MAX_REVISION_LENGTH
            and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value)
            and value.casefold() not in _INVALID_STRINGS
        )
    return False


def revision_matches(document: Any, expected: Any) -> bool:
    if not isinstance(document, dict) or not is_revision(expected):
        return False
    actual = document.get("resumeTimestamp")
    return is_revision(actual) and str(actual) == str(expected)


def require_revision_match(document: Any, expected: Any) -> None:
    """Fail before writing when a requested resume version is not proven."""
    if not revision_matches(document, expected):
        raise ConflictError("104 resume revision missing, invalid or changed")
