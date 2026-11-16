"""104 resume section encoders based on its current frontend request format.

Only the BIO adapter has been matched to the website's current source:
PUT /profile/ajax/resumeByBlock/bio?vno={versionNo}
body {"blockValueList":{"bio":{"bio":{"chi":"...","eng":"..."}}}}

Other fields must not be silently serialized using this adapter; their
frontend mapping and server-side validation can differ substantially.
"""
from __future__ import annotations

from typing import Any

from job_platforms.core.errors import UnsupportedWrite


BIO_PATHS = frozenset((
    "/bio/formData/bio/chi",
    "/bio/formData/bio/eng",
))


def bio_data(document: dict[str, Any]) -> dict[str, str]:
    try:
        values = document["bio"]["formData"]["bio"]
        chi = values["chi"]
        eng = values["eng"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 BIO response shape is not supported") from exc
    if not isinstance(chi, str) or not isinstance(eng, str):
        raise UnsupportedWrite("104 BIO expects string values for chi and eng")
    return {"chi": chi, "eng": eng}


def bio_request_body(document: dict[str, Any]) -> dict:
    """Serialize both biography values, preserving the untouched sibling."""
    return {"blockValueList": {"bio": {"bio": bio_data(document)}}}


def checked_write_paths(operations: list) -> list[str]:
    paths = []
    for operation in operations:
        if operation.op == "test":
            continue
        if operation.op != "replace" or operation.path not in BIO_PATHS:
            raise UnsupportedWrite(
                "Only replacing BIO chi/eng is verified; "
                "other 104 sections need dedicated adapters"
            )
        paths.append(operation.path)
    return sorted(set(paths))
