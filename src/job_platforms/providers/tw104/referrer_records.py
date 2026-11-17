"""104 REFERRER CRUD source-mapped to editor module f5d8.

The UI emits POST/PUT with one referrers[] record, preserving its native
fields except replacing the company selector with company.text. DELETE uses
a sort-ID list. Empty formData is an observed initial state; its first POST
uses the site's first optionsReferrerTheme entry (f5d8 form component).

This adapter does NOT send mail, invite contacts or perform account changes.
Read-only source mapping + synthetic tests, not a real 104 write verification.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

FIELDS = frozenset(("name", "company", "position", "email", "tel", "sort"))
CREATABLE_FIELDS = FIELDS - {"sort"}

# Confirmed against authenticated GET /profile/ajax/inputField on 2026-11-17.
# Keep conservative limits; values are not copied from any user's profile.
FIELD_LIMITS = {
    "name": 30, "company": 35, "position": 20,
    "email": 50, "tel": 50,
}


def _text(value: Any, field: str, *, mandatory: bool = False) -> str:
    if not isinstance(value, str) or (mandatory and not value.strip()):
        raise UnsupportedWrite(f"104 REFERRER {field} must be text")
    if len(value) > FIELD_LIMITS[field]:
        raise UnsupportedWrite(f"104 REFERRER {field} exceeds site field length")
    return value


def _record(record: Any) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise UnsupportedWrite("104 REFERRER unexpected record fields")
    for field in ("name", "company", "position"):
        _text(record[field], field, mandatory=True)
    _text(record["email"], "email")
    _text(record["tel"], "tel")
    if not record["email"].strip() and not record["tel"].strip():
        raise UnsupportedWrite("104 REFERRER requires email or telephone")
    number = record["sort"]
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise UnsupportedWrite("104 REFERRER sort must be a positive integer")
    return deepcopy(record)


def referrer_records(document: dict) -> list[dict]:
    """Accept empty initial formData, or populated native form and theme."""
    try:
        form = document["referrer"]["formData"]
    except (TypeError, KeyError) as exc:
        raise UnsupportedWrite("104 REFERRER section missing") from exc
    if not isinstance(form, dict):
        raise UnsupportedWrite("104 REFERRER formData invalid")
    if not form:
        return []
    if set(form) != {"referrers", "themeChoose"}:
        raise UnsupportedWrite("104 REFERRER formData shape changed")
    theme = form["themeChoose"]
    if not isinstance(theme, dict) or not isinstance(theme.get("selectedTheme"), dict):
        raise UnsupportedWrite("104 REFERRER theme unavailable")
    selected = theme["selectedTheme"].get("value")
    if isinstance(selected, bool) or not isinstance(selected, int) or selected < 1:
        raise UnsupportedWrite("104 REFERRER selectedTheme invalid")
    if not isinstance(form["referrers"], list):
        raise UnsupportedWrite("104 REFERRER records not an array")
    rows = [_record(row) for row in form["referrers"]]
    sorts = [row["sort"] for row in rows]
    allowed = list(range(1, len(rows) + 1))
    if sorts != allowed and sorts != allowed[::-1]:
        raise UnsupportedWrite("104 REFERRER sort ordering unsupported")
    return rows


def _theme(document: dict, options: dict | None) -> int:
    form = document["referrer"]["formData"]
    if form:
        return form["themeChoose"]["selectedTheme"]["value"]
    if not isinstance(options, dict):
        raise UnsupportedWrite("104 REFERRER initial theme needs site options")
    choices = options.get("optionsReferrerTheme")
    if not isinstance(choices, list) or not choices:
        raise UnsupportedWrite("104 REFERRER available themes missing")
    first = choices[0]
    if not isinstance(first, dict) or isinstance(first.get("value"), bool) or not isinstance(first.get("value"), int) or first["value"] < 1:
        raise UnsupportedWrite("104 REFERRER first theme option invalid")
    return first["value"]


def _wire(row: dict, *, include_sort: bool) -> dict:
    record = _record(row)
    result = {key: record[key] for key in ("name", "company", "position", "email", "tel")}
    if include_sort:
        result["sort"] = record["sort"]
    return result


def referrer_operation_body(
    document: dict, action: str, *, changes: dict | None = None,
    position: int | None = None, options: dict | None = None,
) -> dict:
    if action not in ("create", "update", "delete"):
        raise UnsupportedWrite("104 REFERRER unknown operation")
    records = referrer_records(document)
    if action == "delete":
        if changes is not None or isinstance(position, bool) or not isinstance(position, int) or position not in [x["sort"] for x in records]:
            raise UnsupportedWrite("104 REFERRER delete needs existing native sort")
        return {"blockValueList": {"referrer": {"referrers": {"sort": [position]}}}}
    if not isinstance(changes, dict) or not changes or set(changes) - CREATABLE_FIELDS:
        raise UnsupportedWrite("104 REFERRER changes contain unsupported fields")
    if action == "create":
        if position is not None or set(changes) != CREATABLE_FIELDS:
            raise UnsupportedWrite("104 REFERRER create needs all native fields")
        row = {**changes, "sort": len(records) + 1}
    else:
        if isinstance(position, bool) or not isinstance(position, int):
            raise UnsupportedWrite("104 REFERRER update needs current sort")
        current = next((x for x in records if x["sort"] == position), None)
        if current is None:
            raise UnsupportedWrite("104 REFERRER sort not found")
        row = {**current, **changes}
    # Only the matched record is sent; f5d8's postData forwards its sort on
    # update, while on initial create the UI record has no sort.
    wire = _wire(row, include_sort=(action == "update"))
    selected_theme = _theme(document, options)
    return {"blockValueList": {"referrer": {
        "referrers": [wire], "themeChoose": {"selectedTheme": selected_theme},
    }}}


def verify_referrer_operation(
    before: dict, after: dict, action: str, *,
    body: dict, position: int | None,
) -> bool:
    original, current = referrer_records(before), referrer_records(after)
    # The initial formData can become fully populated on first POST.
    before_form = before["referrer"]["formData"]
    after_form = after["referrer"]["formData"]
    if before_form and after_form:
        if before_form["themeChoose"] != after_form["themeChoose"]:
            return False

    def mapped(rows: list[dict]) -> Counter:
        return Counter(json.dumps(
            _wire(row, include_sort=False), ensure_ascii=False, sort_keys=True,
        ) for row in rows)

    if action == "create":
        if len(current) != len(original) + 1:
            return False
        expected = body["blockValueList"]["referrer"]["referrers"][0]
        new_only = mapped(current) - mapped(original)
        return (
            sum(new_only.values()) == 1
            and new_only == Counter({json.dumps(expected, ensure_ascii=False, sort_keys=True): 1})
        )
    if action == "update":
        if len(original) != len(current):
            return False
        old_ids = {row["sort"]: row for row in original}
        new_ids = {row["sort"]: row for row in current}
        if old_ids.keys() != new_ids.keys() or position not in old_ids:
            return False
        if any(old_ids[k] != new_ids[k] for k in old_ids if k != position):
            return False
        expected = body["blockValueList"]["referrer"]["referrers"][0]
        return _wire(new_ids[position], include_sort=True) == expected
    if action == "delete":
        if len(current) != len(original) - 1:
            return False
        removed = next((row for row in original if row["sort"] == position), None)
        return (
            removed is not None
            and mapped(current) == mapped([row for row in original if row is not removed])
        )
    return False
