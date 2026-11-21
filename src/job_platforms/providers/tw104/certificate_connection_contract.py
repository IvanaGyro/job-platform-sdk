"""104 certification-to-resume *association* source-level request planner.

Frontend module 779c:
  SET_CERTIFICATION_CONNECT dispatches api/certificationConnect/put
    with data={"certIds": selectedIDs} and the resume vno;
  DELETE_CERTIFICATION_CONNECT dispatches
    api/certificationConnect/delete with {vno,id: recordID};
  DELETE_CERTIFICATION_OTHER dispatches
    api/certificationConnect/deleteOther with the resume vno.

These are *not* account-global certification create/update/delete.
The deployed API route and populated record GET semantics have not
been verified, so this adapter only prepares typed action metadata.
No network write is permitted by this module.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

MAX_SELECTION = 20  # Source UI importLimit=20 (official certificate editor)


def _id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise UnsupportedWrite("104 certification link ID must be a positive integer")
    return value


def certificate_connect_plan(ids: Any) -> dict:
    """Return exact body and **unresolved frontend action name**, not an URL."""
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SELECTION:
        raise UnsupportedWrite("104 certification selection is invalid")
    selections = [_id(i) for i in ids]
    if len(set(selections)) != len(selections):
        raise UnsupportedWrite("104 certification selection contains duplicates")
    return {
        "frontend_action": "api/certificationConnect/put",
        "method": "PUT",
        "body": {"certIds": deepcopy(selections)},
        "remote_write_enabled": False,
    }


def certificate_disconnect_plan(record_id: Any) -> dict:
    """Disconnect one association, not delete its account-level record."""
    return {
        "frontend_action": "api/certificationConnect/delete",
        "method": "DELETE",
        "record_id": _id(record_id),
        "body": None,
        "remote_write_enabled": False,
    }


def certificate_other_text_disconnect_plan() -> dict:
    """Separate action; do not confuse with whole CERTIFICATE block clear."""
    return {
        "frontend_action": "api/certificationConnect/deleteOther",
        "method": "DELETE",
        "body": None,
        "remote_write_enabled": False,
    }
