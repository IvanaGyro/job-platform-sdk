"""104 CUSTOM CLASSIC/BANNER single-content, no-media guarded CRUD.

Official frontend CUSTOM module 4228 supplies the wire request. Earlier
private reversible raw POST/PUT/DELETE cycles passed for CLASSIC=1 and
BANNER=2, but these SDK wrappers are not independently live verified.
MAGAZINE, IMAGE and all other media operations remain unsupported.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite
from .custom_text_contract import _slot, custom_delete_body
from .custom_themes import (
    _safe_text, _safe_html, _url, _duration, custom_theme_create_body,
)

LAYOUT_THEMES = {1: "CLASSIC", 2: "BANNER"}
_FILE_EMPTY = frozenset({
    "content", "ext", "url", "src", "fileId", "thumbnailStatus",
    "thumbnailUrl", "thumbnailFileId",
})
_DATE_KEYS = frozenset({"startYear", "startMonth", "endYear", "endMonth"})


def _native_content(row: Any) -> dict:
    if not isinstance(row, dict) or set(row) != {
        "duration", "isInProgress", "introduction", "url", "file"
    }:
        raise UnsupportedWrite("104 CUSTOM layout content shape unsupported")
    media = row["file"]
    if not isinstance(media, list) or len(media) != 1 or not isinstance(media[0], dict):
        raise UnsupportedWrite("104 CUSTOM layout must have exactly one no-media entry")
    entry = media[0]
    if (type(entry.get("type")) is not int or entry["type"] != 0
            or set(entry) - _FILE_EMPTY - {"type"}
            or any(v not in (None, "") for k, v in entry.items() if k != "type")):
        raise UnsupportedWrite("104 CUSTOM layout has protected media metadata")
    raw_progress = row["isInProgress"]
    if type(raw_progress) is bool:
        running = raw_progress
    elif type(raw_progress) is int and raw_progress in (0, 1):
        running = bool(raw_progress)
    elif raw_progress == []:
        running = False
    else:
        raise UnsupportedWrite("104 CUSTOM layout progress value unsupported")
    duration = row["duration"]
    if (not isinstance(duration, dict) or not _DATE_KEYS <= duration.keys()
            or set(duration) - _DATE_KEYS - {"index", "durationGroup"}
            or duration.get("index", -1) not in (-1, None)
            or duration.get("durationGroup", {}) not in ({}, None)):
        raise UnsupportedWrite("104 CUSTOM layout date metadata unsupported")
    clean = {}
    for field in ("startYear", "endYear"):
        val = duration[field]
        if val in ({}, None):
            val = ""
        if type(val) is not str:
            raise UnsupportedWrite("104 CUSTOM layout year unsupported")
        clean[field] = val
    for field in ("startMonth", "endMonth"):
        val = duration[field]
        if val in ("", {}, None):
            val = 0
        if type(val) is not int or not 0 <= val <= 12:
            raise UnsupportedWrite("104 CUSTOM layout month unsupported")
        clean[field] = val
    _duration(clean, running)
    if running and (clean["endYear"] or clean["endMonth"]):
        # The outgoing encoder drops end dates for ongoing records. An
        # un-cleared GET must not falsely verify a successful update.
        raise UnsupportedWrite("104 CUSTOM ongoing layout retains unexpected end date")
    return {
        "duration": clean, "isInProgress": running,
        "introduction_html": _safe_html(row["introduction"]),
        "url": _url(row["url"]), "media": {"type": 0},
    }


def layout_form(document: dict, *, slot: int) -> dict | None:
    """Only accept the exact known unencrypted no-media GET shape."""
    number = _slot(slot)
    if not isinstance(document, dict):
        raise UnsupportedWrite("104 CUSTOM layout resume missing")
    key = f"custom{number}"
    if key not in document:
        return None
    section = document[key]
    if not isinstance(section, dict) or set(section) != {"formData"}:
        raise UnsupportedWrite("104 CUSTOM layout native block unsupported")
    form = section["formData"]
    if not isinstance(form, dict) or set(form) != {"custom", "themeChoose"}:
        raise UnsupportedWrite("104 CUSTOM layout native form unsupported")
    custom, theme_group = form["custom"], form["themeChoose"]
    if not isinstance(custom, dict) or set(custom) != {"name", "sort", "content"}:
        raise UnsupportedWrite("104 CUSTOM layout title/sort/content unsupported")
    if type(custom["sort"]) is not int or custom["sort"] != number:
        raise UnsupportedWrite("104 CUSTOM layout sort mismatch")
    if (not isinstance(theme_group, dict)
            or not isinstance(theme_group.get("selectedTheme"), dict)):
        raise UnsupportedWrite("104 CUSTOM layout theme selection unsupported")
    theme = theme_group["selectedTheme"].get("value")
    if type(theme) is not int or theme not in LAYOUT_THEMES:
        raise UnsupportedWrite("104 CUSTOM layout theme unsupported")
    rows = custom["content"]
    if not isinstance(rows, list) or len(rows) != 1:
        raise UnsupportedWrite("104 CUSTOM layout supports exactly one content")
    return {"slot": number, "name": _safe_text(custom["name"], "name", 30, required=True),
            "theme": theme, "content": _native_content(rows[0])}


def layout_operation_body(
    before: dict, action: str, *, slot: int,
    theme: int | None = None, name: str | None = None,
    content: dict | None = None, options: dict | None = None,
) -> dict:
    """Build one native CRUD body after validating existing slot ownership."""
    number = _slot(slot)
    if action not in ("create", "update", "delete") or not isinstance(before, dict):
        raise UnsupportedWrite("104 CUSTOM layout action/resume unsupported")
    if action == "create":
        # Never treat a non-layout or opaque occupied slot as free.
        if f"custom{number}" in before:
            raise UnsupportedWrite("104 CUSTOM layout slot already occupied")
        if type(theme) is not int or theme not in LAYOUT_THEMES or name is None or content is None:
            raise UnsupportedWrite("104 CUSTOM layout create requires theme/name/content")
        selected_theme, selected_name, selected_content = theme, name, content
    else:
        original = layout_form(before, slot=number)
        if original is None:
            raise UnsupportedWrite("104 CUSTOM layout slot absent")
        if action == "delete":
            if any(v is not None for v in (theme, name, content)):
                raise UnsupportedWrite("104 CUSTOM layout delete takes no fields")
            return custom_delete_body(slot=number)
        if theme is not None and (type(theme) is not int or theme != original["theme"]):
            raise UnsupportedWrite("104 CUSTOM layout theme change unsupported")
        if name is None and content is None:
            raise UnsupportedWrite("104 CUSTOM layout update requires changes")
        selected_theme = original["theme"]
        selected_name = original["name"] if name is None else name
        selected_content = original["content"] if content is None else content
    if not isinstance(selected_content, dict) or set(selected_content) != {
        "duration", "isInProgress", "introduction_html", "url", "media"
    } or selected_content["media"] != {"type": 0}:
        raise UnsupportedWrite("104 CUSTOM layout requires one no-media content")
    # A new theme must be present in the current site's catalog. An existing
    # same-theme record can update its own fields without a guessed catalog.
    current_options = options if action == "create" else {
        "optionsCustomTheme": [{"value": selected_theme}]
    }
    return custom_theme_create_body(
        slot=number, name=selected_name, theme=selected_theme,
        contents=[deepcopy(selected_content)], theme_options=current_options,
    )


def verify_layout_mutation(
    before: dict, after: dict, action: str, *, slot: int, body: dict,
) -> bool:
    """Verify target, its entire no-media content and untouched sibling slots."""
    number = _slot(slot)
    target = f"custom{number}"
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    slots = {f"custom{i}" for i in range(1, 7)}
    old_set = set(before) & slots
    new_set = set(after) & slots
    if any(before.get(k) != after.get(k) for k in old_set | new_set if k != target):
        return False
    if action == "delete":
        return target in old_set and target not in new_set
    if (action == "create" and (target in old_set or new_set != old_set | {target})) or (
        action == "update" and (target not in old_set or target not in new_set)
    ):
        return False
    try:
        got = layout_form(after, slot=number)
        desired = body["blockValueList"]["custom"]
        if got is None or got["name"] != desired["custom"]["name"] or got["theme"] != desired["themeChoose"]["selectedTheme"]:
            return False
        wire = custom_theme_create_body(
            slot=number, name=got["name"], theme=got["theme"],
            contents=[got["content"]],
            theme_options={"optionsCustomTheme": [{"value": got["theme"]}]},
        )
    except (UnsupportedWrite, KeyError, TypeError, ValueError):
        return False
    return wire == body
