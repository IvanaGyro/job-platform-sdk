"""Section-level 104 resume serializers derived from the frontend.

Every supported block has its own encoder, allowed JSON Patch paths, and
snapshot extractor for exact read-after-write verification. Unknown sections,
nested operations, or data shapes are rejected before any network write.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite
from .job_condition import (
    EDITABLE_PATHS as JOB_CONDITION_PATHS,
    native_job_condition,
    job_condition_request_body,
)


BIO_PATHS = frozenset((
    "/bio/formData/bio/chi",
    "/bio/formData/bio/eng",
))
CERTIFICATE_PATHS = frozenset((
    "/certificate/formData/certificate/certificates",
    "/certificate/formData/certificate/others",
))
SIDEBAR_PATHS = frozenset(("/sidebar",))
WRITE_PATH_TO_SECTION = {
    **{path: "bio" for path in BIO_PATHS},
    **{path: "certificate" for path in CERTIFICATE_PATHS},
    **{path: "sidebar" for path in SIDEBAR_PATHS},
    **{path: "jobCondition" for path in JOB_CONDITION_PATHS},
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


def sidebar_records(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Source-observed sidebar array with unique, unambiguous entry identifiers."""
    records = document.get("sidebar")
    if not isinstance(records, list):
        raise UnsupportedWrite("104 SIDEBAR is not an array")
    ids = []
    for record in records:
        if not isinstance(record, dict):
            raise UnsupportedWrite("104 SIDEBAR contains a non-object entry")
        identifier = record.get("id")
        if (not isinstance(identifier, (str, int)) or
                isinstance(identifier, bool) or
                isinstance(identifier, str) and not identifier):
            raise UnsupportedWrite("104 SIDEBAR entry has no valid identifier")
        ids.append(identifier)
    # Keep number and string IDs distinct while disallowing duplicates.
    if len(set((type(x).__name__, x) for x in ids)) != len(ids):
        raise UnsupportedWrite("104 SIDEBAR contains duplicate identifiers")
    return deepcopy(records)


def sidebar_data(document: dict[str, Any]) -> dict[str, Any]:
    return {"ids": [item["id"] for item in sidebar_records(document)]}


def validate_section_edit(before: dict, after: dict, section: str) -> None:
    """Prohibit unintended changes to metadata that the upstream PUT discards."""
    if section != "sidebar":
        return
    old = sidebar_records(before)
    new = sidebar_records(after)
    if len(old) != len(new):
        raise UnsupportedWrite("SIDEBAR reorder cannot add or remove records")
    def by_id(records: list[dict]) -> dict[tuple[str, str | int], dict]:
        return {(type(item["id"]).__name__, item["id"]): item for item in records}
    if by_id(old) != by_id(new):
        raise UnsupportedWrite(
            "SIDEBAR only supports reordering existing records; no metadata edits"
        )


def section_data(document: dict[str, Any], section: str) -> dict[str, Any]:
    if section == "bio":
        return bio_data(document)
    if section == "certificate":
        return certificate_data(document)
    if section == "sidebar":
        return sidebar_data(document)
    if section == "jobCondition":
        return native_job_condition(document)
    raise UnsupportedWrite("No verified serializer for this 104 section")


def section_request_body(document: dict[str, Any], section: str) -> dict:
    """Preserve unaffected sibling values inside the same section."""
    if section == "jobCondition":
        return job_condition_request_body(document)
    return {"blockValueList": {section: (
        {"bio": bio_data(document)} if section == "bio"
        else certificate_data(document) if section == "certificate"
        else [{"id": item["id"]} for item in sidebar_records(document)]
             if section == "sidebar"
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
