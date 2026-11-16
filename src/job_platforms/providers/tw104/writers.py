"""Section-level 104 resume serializers derived from the frontend.

Every supported block has its own encoder, allowed JSON Patch paths, and
snapshot extractor for exact read-after-write verification. Unknown sections,
nested operations, or data shapes are rejected before any network write.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite


BIO_PATHS = frozenset((
    "/bio/formData/bio/chi",
    "/bio/formData/bio/eng",
))
CERTIFICATE_PATHS = frozenset((
    "/certificate/formData/certificate/certificates",
    "/certificate/formData/certificate/others",
))
WRITE_PATH_TO_SECTION = {
    **{path: "bio" for path in BIO_PATHS},
    **{path: "certificate" for path in CERTIFICATE_PATHS},
}


def bio_data(document: dict[str, Any]) -> dict[str, str]:
    try:
        value = document["bio"]["formData"]["bio"]
        chi, eng = value["chi"], value["eng"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 BIO response shape is not supported") from exc
    if not isinstance(chi, str) or not isinstance(eng, str):
        raise UnsupportedWrite("104 BIO expects string values for both languages")
    return {"chi": chi, "eng": eng}


def certificate_data(document: dict[str, Any]) -> dict[str, Any]:
    try:
        value = document["certificate"]["formData"]["certificate"]
        certificates, others = value["certificates"], value["others"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 CERTIFICATE response shape is not supported") from exc
    if not isinstance(certificates, list) or not isinstance(others, str):
        raise UnsupportedWrite("104 CERTIFICATE expects list and string fields")
    if not all(isinstance(item, dict) for item in certificates):
        raise UnsupportedWrite("104 CERTIFICATE expects object entries")
    return {"certificates": deepcopy(certificates), "others": others}


def section_data(document: dict[str, Any], section: str) -> dict[str, Any]:
    if section == "bio":
        return bio_data(document)
    if section == "certificate":
        return certificate_data(document)
    raise UnsupportedWrite("No verified serializer for this 104 section")


def section_request_body(document: dict[str, Any], section: str) -> dict:
    """Preserve unaffected sibling values inside the same section."""
    return {"blockValueList": {section: (
        {"bio": bio_data(document)} if section == "bio"
        else certificate_data(document) if section == "certificate"
        else _unsupported()
    )}}


def _unsupported():
    raise UnsupportedWrite("No 104 request body encoder for this section")


def bio_request_body(document: dict[str, Any]) -> dict:
    """Backward-compatible BIO serializer alias."""
    return section_request_body(document, "bio")


def checked_write_paths(operations: list) -> list[str]:
    """Only strict complete-field replacement is currently supported."""
    paths = []
    for operation in operations:
        if operation.op == "test":
            continue
        if operation.op != "replace" or operation.path not in WRITE_PATH_TO_SECTION:
            raise UnsupportedWrite(
                "This field or JSON Patch operation has not been mapped "
                "to an upstream 104 write request"
            )
        paths.append(operation.path)
    return list(dict.fromkeys(paths))


def changed_sections(paths: list[str]) -> list[str]:
    """Order sections by their first modified field, not by name."""
    return list(dict.fromkeys(WRITE_PATH_TO_SECTION[path] for path in paths))
