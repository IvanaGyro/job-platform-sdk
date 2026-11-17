"""104 PROJECT native no-media CRUD, with first-empty-form initialization.

Source: public 104 frontend module 1d22 postData() and the editor's
create/update/delete actions. File/image/video uploads are deliberately
outside this adapter. Creation accepts only no-asset PROJECT entries.
Updates are allowed only when the existing entry has no media, so they
cannot silently discard a previously uploaded cover/video.

The user's test resume's PROJECT formData was empty in a live read-only
GET; POST/PUT/DELETE have not been live-verified or restored.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from job_platforms.core.errors import UnsupportedWrite

FORM_FIELDS = frozenset({"name", "duration", "isInProgress", "introduction", "url"})
GET_FIELDS = FORM_FIELDS | {"sort", "img"}
DURATION_FIELDS = frozenset({"startYear", "startMonth", "endYear", "endMonth"})


def _text(value: Any, field: str, max_chars: int, *, required: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > max_chars
            or (required and not value.strip())):
        raise UnsupportedWrite(f"104 PROJECT invalid {field}")
    return value


def _month(value: Any) -> str | int | None:
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        if "value" not in value:
            raise UnsupportedWrite("104 PROJECT month selector has no value")
        value = value["value"]
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise UnsupportedWrite("104 PROJECT invalid month")
    if str(value) == "":
        return ""
    try:
        number = int(value)
    except ValueError:
        raise UnsupportedWrite("104 PROJECT month not numeric") from None
    if not 1 <= number <= 12:
        raise UnsupportedWrite("104 PROJECT month out of range")
    return value


def _year(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise UnsupportedWrite("104 PROJECT invalid year")
    text = str(value)
    if len(text) != 4 or not text.isdecimal():
        raise UnsupportedWrite("104 PROJECT year must be four digits")
    if not 1900 <= int(text) <= date.today().year + 2:
        raise UnsupportedWrite("104 PROJECT year outside conservative range")
    return text


def _progress(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1) and isinstance(value, int):
        return bool(value)
    if isinstance(value, list) and len(value) <= 1:
        # The frontend maps an empty selection to 0, a nonempty one to 1.
        return bool(value)
    raise UnsupportedWrite("104 PROJECT unsupported in-progress state")


def _fields(data: Any, *, first: bool) -> dict:
    if not isinstance(data, dict) or (
        set(data) != FORM_FIELDS if first else not set(data) <= FORM_FIELDS
    ):
        raise UnsupportedWrite("104 PROJECT unsupported editable field set")
    if not first and not data:
        raise UnsupportedWrite("104 PROJECT changes are empty")
    values = deepcopy(data)
    if "name" in values:
        _text(values["name"], "name", 120, required=True)
    if "introduction" in values:
        _text(values["introduction"], "introduction", 4000)
    if "url" in values:
        url = _text(values["url"], "url", 200)
        if url:
            parts = urlsplit(url)
            if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
                raise UnsupportedWrite("104 PROJECT URL must be http(s)")
    if "isInProgress" in values:
        values["isInProgress"] = _progress(values["isInProgress"])
    if "duration" in values:
        duration = values["duration"]
        if not isinstance(duration, dict) or set(duration) != DURATION_FIELDS:
            raise UnsupportedWrite("104 PROJECT duration must have four fields")
        values["duration"] = {
            "startYear": _year(duration["startYear"]),
            "startMonth": _month(duration["startMonth"]),
            "endYear": _year(duration["endYear"]),
            "endMonth": _month(duration["endMonth"]),
        }
    return values


def project_record(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != GET_FIELDS:
        raise UnsupportedWrite("104 PROJECT populated GET shape unverified")
    position = value.get("sort")
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise UnsupportedWrite("104 PROJECT invalid sort")
    _fields({k: value[k] for k in FORM_FIELDS}, first=True)
    image = value["img"]
    if not isinstance(image, dict) or not isinstance(image.get("type"), int):
        raise UnsupportedWrite("104 PROJECT unknown media object")
    return deepcopy(value)


def project_records(doc: dict) -> list[dict]:
    try:
        form = doc["project"]["formData"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 PROJECT section missing") from exc
    if not isinstance(form, dict):
        raise UnsupportedWrite("104 PROJECT formData invalid")
    if not form:
        return []
    if set(form) != {"projects", "themeChoose"}:
        raise UnsupportedWrite("104 PROJECT unexpected form fields")
    theme = form["themeChoose"]
    if not isinstance(theme, dict) or not isinstance(theme.get("selectedTheme"), dict):
        raise UnsupportedWrite("104 PROJECT selectedTheme missing")
    option = theme["selectedTheme"].get("value")
    if isinstance(option, bool) or not isinstance(option, int) or option < 1:
        raise UnsupportedWrite("104 PROJECT invalid theme")
    if not isinstance(form["projects"], list):
        raise UnsupportedWrite("104 PROJECT records not an array")
    rows = [project_record(x) for x in form["projects"]]
    numbers = [x["sort"] for x in rows]
    forward = list(range(1, len(rows) + 1))
    if numbers != forward and numbers != forward[::-1]:
        raise UnsupportedWrite("104 PROJECT sort identifiers unsupported")
    return rows


def _theme(doc: dict, options: dict | None) -> int:
    form = doc["project"]["formData"]
    if form:
        return form["themeChoose"]["selectedTheme"]["value"]
    if not isinstance(options, dict):
        raise UnsupportedWrite("104 PROJECT needs default theme options")
    choices = options.get("optionsProjectTheme")
    if not isinstance(choices, list) or not choices:
        raise UnsupportedWrite("104 PROJECT no themes available")
    first = choices[0]
    if (not isinstance(first, dict) or isinstance(first.get("value"), bool)
            or not isinstance(first.get("value"), int) or first["value"] < 1):
        raise UnsupportedWrite("104 PROJECT initial theme invalid")
    return first["value"]


def _wire(data: dict, *, include_sort: bool) -> dict:
    value = _fields({k: data[k] for k in FORM_FIELDS}, first=True)
    img = data.get("img", {"type": 0})
    if not isinstance(img, dict) or img.get("type") != 0:
        raise UnsupportedWrite("104 PROJECT media editing requires a separate verified adapter")
    duration = value["duration"]
    if value["isInProgress"]:
        duration["endYear"] = ""
        duration["endMonth"] = ""
    result = {
        "name": value["name"],
        "duration": duration,
        "isInProgress": int(value["isInProgress"]),
        "introduction": value["introduction"],
        "url": value["url"],
        # Derived from 1d22 postData() on an image of type NONE (0).
        "file": {"type": 0, "content": ""},
    }
    if include_sort:
        result["sort"] = data["sort"]
    return result


def project_operation_body(
    doc: dict, action: str, *, changes: dict | None = None,
    position: int | None = None, options: dict | None = None,
) -> dict:
    if action not in ("create", "update", "delete"):
        raise UnsupportedWrite("104 PROJECT action unsupported")
    existing = project_records(doc)
    if action == "create" and len(existing) >= 6:
        raise UnsupportedWrite("104 PROJECT editor permits at most 6 entries")
    if action == "delete":
        if (changes is not None or isinstance(position, bool)
                or not isinstance(position, int)
                or position not in {x["sort"] for x in existing}):
            raise UnsupportedWrite("104 PROJECT delete requires current sort")
        return {"blockValueList": {"project": {"projects": {"sort": [position]}}}}
    if action == "create":
        if position is not None:
            raise UnsupportedWrite("104 PROJECT create does not accept a sort")
        editable = _fields(changes, first=True)
        row = {**editable, "img": {"type": 0}}
    else:
        if isinstance(position, bool) or not isinstance(position, int):
            raise UnsupportedWrite("104 PROJECT update requires an existing sort")
        original = next((x for x in existing if x["sort"] == position), None)
        if original is None:
            raise UnsupportedWrite("104 PROJECT existing sort not found")
        fields = _fields(changes, first=False)
        row = {**original, **fields}
        # All edits must preserve the old no-media cover. File uploads/removals
        # are a separate workflow with different remote semantics.
    payload = _wire(row, include_sort=(action == "update"))
    return {"blockValueList": {"project": {
        "projects": [payload],
        "themeChoose": {"selectedTheme": _theme(doc, options)},
    }}}


def _content(row: dict) -> dict:
    value = _wire(row, include_sort=False)
    return value


def verify_project_operation(
    before: dict, after: dict, action: str, *,
    body: dict, position: int | None,
) -> bool:
    old, new = project_records(before), project_records(after)
    old_form, new_form = before["project"]["formData"], after["project"]["formData"]
    if old_form and new_form and old_form["themeChoose"] != new_form["themeChoose"]:
        return False
    if action == "create":
        if len(new) != len(old) + 1:
            return False
        expected = body["blockValueList"]["project"]["projects"][0]
        from collections import Counter
        import json
        def bag(rows):
            return Counter(json.dumps(
                _content(x), sort_keys=True, ensure_ascii=False
            ) for x in rows)
        addition = bag(new) - bag(old)
        return addition == Counter({
            json.dumps(expected, sort_keys=True, ensure_ascii=False): 1
        })
    if action == "update":
        if len(new) != len(old):
            return False
        old_map = {x["sort"]: x for x in old}
        new_map = {x["sort"]: x for x in new}
        if old_map.keys() != new_map.keys():
            return False
        if any(old_map[i] != new_map[i] for i in old_map if i != position):
            return False
        return _wire(new_map[position], include_sort=True) == (
            body["blockValueList"]["project"]["projects"][0]
        )
    if action == "delete":
        if len(new) != len(old) - 1:
            return False
        expected = [_content(x) for x in old if x["sort"] != position]
        return [_content(x) for x in new] == expected
    return False
