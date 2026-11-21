"""104-native SKILL create/update/delete requests from the site's Vuex store.

Frontend action contracts:
  CREATE POST /profile/ajax/resumeByBlock/skill?vno=...
  UPDATE PUT  /profile/ajax/resumeByBlock/skill?vno=...
  DELETE DELETE /profile/ajax/resumeByBlock/skill?vno=...

Create/update: {"blockValueList":{"skill":{"skills":[{sort?,name,tag,desc}],
"themeChoose":{"selectedTheme":value}}}}
Delete: {"blockValueList":{"skill":{"skills":{"sort":[one_based_position]}}}}

Sort reordering is a separate swapRecordBySort request, not implemented here.
The format is source-observed, NOT yet live write-verified.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite


def _record(record: Any) -> dict:
    if not isinstance(record, dict) or set(record) != {"name", "desc", "sort", "tag"}:
        raise UnsupportedWrite("104 SKILL record shape is not supported")
    if not isinstance(record["name"], str) or not record["name"].strip():
        raise UnsupportedWrite("104 SKILL name must be a nonempty string")
    if not isinstance(record["desc"], str):
        raise UnsupportedWrite("104 SKILL description must be a string")
    if isinstance(record["sort"], bool) or not isinstance(record["sort"], int) or record["sort"] < 1:
        raise UnsupportedWrite("104 SKILL sort must be a positive integer")
    tags = record["tag"]
    if not isinstance(tags, list):
        raise UnsupportedWrite("104 SKILL tag must be an array")
    if not all(isinstance(t, dict) and set(t) == {"text", "value"}
               and isinstance(t["text"], str) and isinstance(t["value"], str)
               for t in tags):
        raise UnsupportedWrite("104 SKILL tags require text and value strings")
    return deepcopy(record)


def skill_list(document: dict) -> list[dict]:
    try:
        form = document["skill"]["formData"]
        records = form["skills"]
        selected_theme = form["themeChoose"]["selectedTheme"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 SKILL native form is missing") from exc
    if not isinstance(records, list):
        raise UnsupportedWrite("104 SKILL native records must be an array")
    if not isinstance(selected_theme, dict) or not isinstance(selected_theme.get("value"), int):
        raise UnsupportedWrite("104 SKILL theme is not a selector")
    items = [_record(record) for record in records]
    sorts = [item["sort"] for item in items]
    if sorts != list(range(1, len(items) + 1)):
        raise UnsupportedWrite("104 SKILL sort numbers are not sequential")
    return items


def _theme(document: dict) -> int:
    value = document["skill"]["formData"]["themeChoose"]["selectedTheme"]["value"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise UnsupportedWrite("104 SKILL selectedTheme is invalid")
    return value


def _fields(changes: dict, *, create: bool) -> dict:
    if not isinstance(changes, dict) or not changes:
        raise UnsupportedWrite("104 SKILL changes must be a nonempty object")
    if set(changes) - {"name", "desc", "tag"}:
        raise UnsupportedWrite("104 SKILL unexpected editable fields")
    if create and "name" not in changes:
        raise UnsupportedWrite("104 SKILL create requires name")
    if create:
        base = {
            "name": changes.get("name", ""),
            "desc": changes.get("desc", ""),
            "tag": changes.get("tag", []),
            "sort": 1,
        }
        _record(base)
    return deepcopy(changes)


def skill_operation_body(
    document: dict, action: str, *,
    changes: dict | None = None, position: int | None = None,
) -> dict:
    """Return exact source-mapped JSON, and reject unsafe operations."""
    if action not in {"create", "update", "delete"}:
        raise UnsupportedWrite("104 SKILL unknown operation")
    records = skill_list(document)
    if action != "create" and (
        isinstance(position, bool) or not isinstance(position, int) or
        not 1 <= position <= len(records)
    ):
        raise UnsupportedWrite("104 SKILL position must identify an existing record")
    if action == "create":
        values = _fields(changes, create=True)
        record = {"name": values["name"], "desc": values.get("desc", ""),
                  "tag": values.get("tag", [])}
        # Validate complete final record using a synthetic one-based position.
        _record({**record, "sort": 1})
        return {"blockValueList": {"skill": {
            "skills": [record],
            "themeChoose": {"selectedTheme": _theme(document)},
        }}}
    if action == "delete":
        if changes is not None:
            raise UnsupportedWrite("104 SKILL delete does not accept a body")
        return {"blockValueList": {"skill": {"skills": {"sort": [position]}}}}
    values = _fields(changes, create=False)
    original = records[position - 1]
    record = {**original, **values}
    _record(record)
    return {"blockValueList": {"skill": {
        "skills": [record],
        "themeChoose": {"selectedTheme": _theme(document)},
    }}}


def verify_skill_operation(
    before: dict, after: dict, action: str, *,
    body: dict, position: int | None,
) -> bool:
    """No other skill record may change (ignoring expected renumbering)."""
    original = skill_list(before)
    current = skill_list(after)
    if action == "create":
        if len(current) != len(original) + 1:
            return False
        if current[:-1] != original:
            return False
        expected = body["blockValueList"]["skill"]["skills"][0]
        return all(current[-1].get(k) == expected[k] for k in ("name", "desc", "tag"))
    if action == "update":
        if len(current) != len(original):
            return False
        expected = body["blockValueList"]["skill"]["skills"][0]
        if any(current[i] != original[i] for i in range(len(current)) if i != position - 1):
            return False
        return all(current[position - 1].get(k) == expected[k]
                   for k in ("name", "desc", "tag", "sort"))
    if action == "delete":
        if len(current) != len(original) - 1:
            return False
        expected = original[:position-1] + original[position:]
        # Deletion naturally reassigns one-based sort positions.
        return [
            {k: v for k, v in record.items() if k != "sort"}
            for record in current
        ] == [
            {k: v for k, v in record.items() if k != "sort"}
            for record in expected
        ]
    return False
