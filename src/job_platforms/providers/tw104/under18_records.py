"""Strict source-mapped under-18 identity verification form writer.

Retained 104 frontend Vuex source (~module 13ea in 2026-11 bundle) sends
POST (CREATE) or PUT (UPDATE) to resumeByBlock/under18 with exactly three
fields. The user's authorized test resume did *not* include UNDER18; these
serializers and GET contracts are synthetic-tested ONLY. All operations
require explicit caller consent and must avoid logging identity evidence.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite
from .patch_verification import PRESERVE_BLOCKS, stable_block_equal

FIELDS = frozenset({"birthdayDocument", "idType", "selfIdentityConfirmed"})
# Defensive client-side input bounds, not the site's published limits.
DOCUMENT_MAX_LENGTH = 1024
ID_TYPE_MAX = 1000


def under18_fields(value: Any) -> dict:
    """Validate the native three-field request, never stringify/echo values."""
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise UnsupportedWrite("104 UNDER18 requires all three native fields")
    document, identity, confirmed = (
        value["birthdayDocument"], value["idType"], value["selfIdentityConfirmed"],
    )
    if (type(document) is not str or len(document) > DOCUMENT_MAX_LENGTH
            or any(ord(char) < 32 or ord(char) == 127 for char in document)):
        raise UnsupportedWrite("104 UNDER18 birthday document must be bounded text")
    if type(identity) is not int or not 0 <= identity <= ID_TYPE_MAX:
        raise UnsupportedWrite("104 UNDER18 identity type must be a numeric selector")
    if type(confirmed) is not bool:
        raise UnsupportedWrite("104 UNDER18 identity confirmation must be Boolean")
    return deepcopy(value)


def under18_native_form(document: Any) -> dict | None:
    """Return exact current native identity form or None if uninitialized."""
    if not isinstance(document, dict):
        raise UnsupportedWrite("104 UNDER18 resume response missing")
    if "under18" not in document:
        return None
    section = document["under18"]
    if not isinstance(section, dict) or not isinstance(section.get("formData"), dict):
        raise UnsupportedWrite("104 UNDER18 section shape unsupported")
    form = section["formData"]
    if not form:
        return None
    if set(form) != {"under18"}:
        raise UnsupportedWrite("104 UNDER18 unknown native fields")
    return under18_fields(form["under18"])


def under18_operation_body(
    before: dict, action: str, *, changes: dict,
) -> dict:
    """Exact frontend Vuex POST/PUT JSON. No implied default legal assent."""
    if action not in ("create", "update"):
        raise UnsupportedWrite("104 UNDER18 only supports source-mapped POST/PUT")
    previous = under18_native_form(before)
    if action == "create" and previous is not None:
        raise UnsupportedWrite("104 UNDER18 already populated")
    if action == "update" and previous is None:
        raise UnsupportedWrite("104 UNDER18 not initialized")
    fields = under18_fields(changes)
    if action == "update" and fields == previous:
        raise UnsupportedWrite("104 UNDER18 update makes no change")
    return {"blockValueList": {"under18": fields}}


def verify_under18_operation(
    before: dict, after: dict, action: str, *, body: dict,
) -> bool:
    """Read back exact identity metadata and preserve all unrelated blocks."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    try:
        old = under18_native_form(before)
        new = under18_native_form(after)
        expected = under18_fields(body["blockValueList"]["under18"])
        if (action == "create" and old is not None) or (
            action == "update" and old is None
        ) or new != expected:
            return False
        if not all(stable_block_equal(before, after, section)
                   for section in PRESERVE_BLOCKS if section != "under18"):
            return False
        # Preserve existing non-formData identity section metadata, too.
        if "under18" in before and "under18" in after:
            orig = deepcopy(before["under18"])
            next_value = deepcopy(after["under18"])
            orig.pop("formData", None)
            next_value.pop("formData", None)
            if orig != next_value:
                return False
        return True
    except (UnsupportedWrite, KeyError, TypeError, ValueError, AttributeError):
        return False
