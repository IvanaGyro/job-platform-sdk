"""104-native EDUCATION record serializer and operation verification.

Derived from the site's Vuex EDUCATION store, not a cross-platform model.
Record fields are the *native GET shape*; the serializer converts them into
the frontend's POST/PUT payload with scalar selectors and department IDs.
No real write verification yet; unknown structures are rejected.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

# Values defined by the 104 frontend EDUCATION constants module (e583).
GENERAL_EDUCATION_LEVEL = 11
STILL_IN_SCHOOL_STATUS = 3
ABROAD_REGION = 7001053000

NATIVE_FIELDS = frozenset((
    "schoolId", "name", "departments", "highest", "duration",
    "status", "inSchoolStatus", "region", "foreign", "sort",
))
EDITABLE_FIELDS = NATIVE_FIELDS - {"sort"}


def _scalar(value: Any, label: str, *, nullable: bool = False) -> Any:
    if value is None and nullable:
        return value
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise UnsupportedWrite(f"104 EDUCATION {label} requires scalar ID/text")
    return value


def _selected(option: Any, label: str, *, nullable: bool = False) -> Any:
    if nullable and option in (None, {}, ""):
        return ""
    if not isinstance(option, dict) or "value" not in option:
        raise UnsupportedWrite(f"104 EDUCATION {label} must have value")
    return _scalar(option["value"], label)


def _category_list(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise UnsupportedWrite(f"104 EDUCATION {label} must be an array")
    result = []
    for entry in value:
        if not isinstance(entry, dict) or "no" not in entry:
            raise UnsupportedWrite(f"104 EDUCATION {label} entries require no")
        result.append(_scalar(entry["no"], label))
    return result


def education_record(value: Any) -> dict:
    """Validate the native GET record without mutating it."""
    if not isinstance(value, dict) or set(value) != NATIVE_FIELDS:
        raise UnsupportedWrite("104 EDUCATION record shape is not supported")
    if not isinstance(value["name"], str) or not value["name"].strip():
        raise UnsupportedWrite("104 EDUCATION school name is required")
    _scalar(value["schoolId"], "schoolId", nullable=True)
    for key in ("highest", "status", "region"):
        _selected(value[key], key)
    _selected(value["inSchoolStatus"], "inSchoolStatus", nullable=True)
    if (isinstance(value["sort"], bool) or
            not isinstance(value["sort"], int) or value["sort"] < 1):
        raise UnsupportedWrite("104 EDUCATION sort must be 1-based")
    duration = value["duration"]
    if not isinstance(duration, dict) or set(duration) != {
        "startYear", "startMonth", "endYear", "endMonth"
    }:
        raise UnsupportedWrite("104 EDUCATION duration shape is unsupported")
    for field in ("startYear", "endYear"):
        _scalar(duration[field], field, nullable=True)
    for field in ("startMonth", "endMonth"):
        _selected(duration[field], field, nullable=True)
    departments = value["departments"]
    if not isinstance(departments, list) or not departments:
        raise UnsupportedWrite("104 EDUCATION needs a department")
    for item in departments:
        if not isinstance(item, dict) or set(item) != {"name", "type"}:
            raise UnsupportedWrite("104 EDUCATION department shape is unsupported")
        if not isinstance(item["name"], str):
            raise UnsupportedWrite("104 EDUCATION department name must be a string")
        _category_list(item["type"], "department type")
    _category_list(value["foreign"], "foreign")
    return deepcopy(value)


def education_list(document: dict) -> list[dict]:
    try:
        form=document["education"]["formData"]
        items=form["educations"]
        theme=form["themeChoose"]["selectedTheme"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 EDUCATION formData is unavailable") from exc
    _selected(theme, "theme")
    if not isinstance(items, list):
        raise UnsupportedWrite("104 EDUCATION records must be an array")
    records=[education_record(item) for item in items]
    if [record["sort"] for record in records] != list(range(1,len(records)+1)):
        raise UnsupportedWrite("104 EDUCATION record order is not sequential")
    return records


def education_wire_record(value: dict) -> dict:
    """Exact logic from the EDUCATION frontend postData() transformation."""
    record=education_record(value)
    highest=_selected(record["highest"], "highest")
    depts=[
        {"name": x["name"], "type": _category_list(x["type"], "department type")}
        for x in record["departments"]
    ]
    if str(highest)==str(GENERAL_EDUCATION_LEVEL):
        depts=[{"name": record["departments"][0]["name"], "type": []}]
    duration=record["duration"]
    status=_selected(record["status"], "status")
    region=_selected(record["region"], "region")
    in_school=(
        _selected(record["inSchoolStatus"], "inSchoolStatus", nullable=True)
        if str(status)==str(STILL_IN_SCHOOL_STATUS) else ""
    )
    return {
        "schoolId": record["schoolId"] or "",
        "name": record["name"],
        "departments": depts,
        "highest": highest,
        "duration": {
            "startYear": duration["startYear"] or "",
            "startMonth": _selected(duration["startMonth"], "startMonth", nullable=True),
            "endYear": duration["endYear"] or "",
            "endMonth": _selected(duration["endMonth"], "endMonth", nullable=True),
        },
        "status": status,
        "inSchoolStatus": in_school,
        "foreign": ([ABROAD_REGION] if str(region)==str(ABROAD_REGION)
                    else _category_list(record["foreign"], "foreign")),
        "sort": record["sort"],
    }


def education_operation_body(
    doc: dict, action: str, *, changes: dict | None = None,
    position: int | None = None,
) -> dict:
    if action not in ("create","update","delete"):
        raise UnsupportedWrite("Unsupported 104 EDUCATION action")
    records=education_list(doc)
    if action == "delete":
        if changes is not None or isinstance(position,bool) or not isinstance(position,int) or not 1 <= position <= len(records):
            raise UnsupportedWrite("104 EDUCATION delete needs existing position")
        return {"blockValueList":{"education":{"educations":{"sort":[position]}}}}
    if not isinstance(changes,dict) or not changes:
        raise UnsupportedWrite("104 EDUCATION changes must be an object")
    if set(changes)-EDITABLE_FIELDS:
        raise UnsupportedWrite("104 EDUCATION change contains unknown/read-only fields")
    if action == "create":
        if position is not None or set(changes)!=EDITABLE_FIELDS:
            raise UnsupportedWrite("104 EDUCATION create needs all native fields")
        row=education_record({**changes,"sort":len(records)+1})
    else:
        if isinstance(position,bool) or not isinstance(position,int) or not 1 <= position <= len(records):
            raise UnsupportedWrite("104 EDUCATION update needs existing position")
        row=education_record({**records[position-1],**changes})
    payload=education_wire_record(row)
    if action == "create":
        payload.pop("sort")  # frontend uses undefined for unsorted inserts
    theme=_selected(doc["education"]["formData"]["themeChoose"]["selectedTheme"],"theme")
    return {"blockValueList":{"education":{
        "educations":[payload],
        "themeChoose":{"selectedTheme":theme}
    }}}


def _without_sort(value: dict) -> dict:
    data=education_wire_record(value)
    data.pop("sort",None)
    return data


def verify_education_operation(before: dict, after: dict, action: str, *,
                               body: dict, position: int | None) -> bool:
    old=education_list(before)
    new=education_list(after)
    if action == "create":
        if len(new)!=len(old)+1 or [_without_sort(x) for x in new[:-1]] != [_without_sort(x) for x in old]:
            return False
        expected=body["blockValueList"]["education"]["educations"][0]
        return _without_sort(new[-1]) == expected
    if action == "update":
        if len(new)!=len(old) or any(
            _without_sort(new[i])!=_without_sort(old[i])
            for i in range(len(old)) if i!=position-1
        ):
            return False
        expected=body["blockValueList"]["education"]["educations"][0]
        return education_wire_record(new[position-1]) == expected
    if action == "delete":
        if len(new)!=len(old)-1:
            return False
        expected=old[:position-1]+old[position:]
        return [_without_sort(x) for x in new] == [_without_sort(x) for x in expected]
    return False
