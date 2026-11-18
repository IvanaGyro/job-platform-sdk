"""104-native EXPERIENCE record CRUD (source-mapped; selected live verified).

104 editor frontend: module f30d, postData(), /resumeByBlock/experience.
It rejects unknown fields and selector variants, but accepts any ordering
of distinct, contiguous server sort keys. An authorized 104 POST with
companyVisibility=True completed SDK create/delete/read-back/restore on
2026-11-19. A previous POST with companyVisibility=False was persisted as
True; until upstream honors false, a private-company CREATE must fail closed.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

NATIVE_FIELDS = frozenset((
    "companyName", "custNo", "invoice", "logo", "industry",
    "companyScale", "jobName", "workArea", "jobType", "jobCat",
    "duration", "description", "skill", "management", "salary",
    "companyVisibility", "stillWork", "salaryVisibility", "sort",
))
EDITABLE_FIELDS = NATIVE_FIELDS - {"sort", "logo"}
SALARIED_JOB_TYPES = frozenset((1, 3))  # c7c7.g and c7c7.h
PART_TIME_JOB_TYPE = 2                 # c7c7.i


def _scalar(value: Any, name: str, *, empty: bool = True) -> str | int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise UnsupportedWrite(f"104 EXPERIENCE {name} must be string/int")
    if not empty and (value == "" or value == 0):
        raise UnsupportedWrite(f"104 EXPERIENCE {name} is required")
    return value


def _select(value: Any, name: str, *, optional: bool = False) -> str | int:
    if optional and value in (None, {}, [], ""):
        return ""
    if not isinstance(value, dict) or not {"value", "text"} <= value.keys():
        raise UnsupportedWrite(f"104 EXPERIENCE {name} is not a selector")
    return _scalar(value["value"], name)


def _category(value: Any, name: str) -> str | int:
    if not isinstance(value, list) or len(value) > 1:
        raise UnsupportedWrite(f"104 EXPERIENCE {name} category cardinality changed")
    if not value:
        return ""
    entry = value[0]
    if not isinstance(entry, dict) or "no" not in entry:
        raise UnsupportedWrite(f"104 EXPERIENCE {name} category entry changed")
    return _scalar(entry["no"], name)


def _text(value: Any, name: str, *, required: bool = False) -> str:
    if not isinstance(value, str) or required and not value.strip():
        raise UnsupportedWrite(f"104 EXPERIENCE {name} must be text")
    return value


def _company_scale(value: Any) -> str | int:
    if isinstance(value, dict):
        return _select(value, "companyScale", optional=True)
    return _scalar(value, "companyScale")


def experience_record(record: Any) -> dict:
    if not isinstance(record, dict) or set(record) != NATIVE_FIELDS:
        raise UnsupportedWrite("104 EXPERIENCE native record shape changed")
    for key in ("companyName", "jobName"):
        _text(record[key], key, required=True)
    for key in ("logo", "description"):
        _text(record[key], key)
    for key in ("custNo", "invoice"):
        _scalar(record[key], key)
    _company_scale(record["companyScale"])
    job_type = _select(record["jobType"], "jobType")
    if job_type not in SALARIED_JOB_TYPES | {PART_TIME_JOB_TYPE}:
        raise UnsupportedWrite("104 EXPERIENCE unsupported employment type")
    for key in ("industry", "workArea", "jobCat"):
        _category(record[key], key)
    duration = record["duration"]
    if not isinstance(duration, dict) or set(duration) != {
        "startYear", "startMonth", "endYear", "endMonth"
    }:
        raise UnsupportedWrite("104 EXPERIENCE unsupported duration")
    _text(duration["startYear"], "startYear", required=True)
    _text(duration["endYear"], "endYear")
    _select(duration["startMonth"], "startMonth")
    _select(duration["endMonth"], "endMonth", optional=True)
    skill = record["skill"]
    if not isinstance(skill, list) or not all(
        isinstance(item, dict) and {"text", "value"} <= item.keys()
        and isinstance(item["text"], str) and isinstance(item["value"], str)
        for item in skill
    ):
        raise UnsupportedWrite("104 EXPERIENCE invalid skill tags")
    _select(record["management"], "management", optional=True)
    salary = record["salary"]
    if not isinstance(salary, dict) or set(salary) != {
        "monthPay", "yearPay", "jobParttimeType", "jobParttimePay"
    }:
        raise UnsupportedWrite("104 EXPERIENCE unsupported salary shape")
    for key in ("monthPay", "yearPay", "jobParttimePay"):
        _scalar(salary[key], key)
    _select(salary["jobParttimeType"], "jobParttimeType", optional=True)
    for key in ("companyVisibility", "stillWork", "salaryVisibility"):
        if not isinstance(record[key], bool):
            raise UnsupportedWrite(f"104 EXPERIENCE {key} must be boolean")
    if isinstance(record["sort"], bool) or not isinstance(record["sort"], int) or record["sort"] < 1:
        raise UnsupportedWrite("104 EXPERIENCE sort must be positive")
    return deepcopy(record)


def experience_list(document: dict) -> list[dict]:
    try:
        form = document["experience"]["formData"]
        records = form["experiences"]
        theme = form["themeChoose"]["selectedTheme"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 EXPERIENCE formData missing") from exc
    _select(theme, "selectedTheme")
    if not isinstance(records, list):
        raise UnsupportedWrite("104 EXPERIENCE records must be an array")
    rows = [experience_record(item) for item in records]
    # The site's GET may reorder array positions independently of the
    # server-side sort keys. Live 104 observations included both
    # [4,3,2,1] and [4,5,3,2,1] after adding record sort=5.
    # Record operations target sort, NEVER the Python list index.
    # Reject duplicates, gaps and unexpected keys, but accept any
    # permutation of the exact contiguous 1-based identifier set.
    observed = [x["sort"] for x in rows]
    if sorted(observed) != list(range(1, len(rows) + 1)):
        raise UnsupportedWrite("104 EXPERIENCE sort identifiers are not a unique contiguous set")
    return rows


def experience_wire_record(row: dict) -> dict:
    """Reconstruct the f30d postData() record, without mutating the source."""
    r = experience_record(row)
    job_type = _select(r["jobType"], "jobType")
    salary = r["salary"]
    duration = r["duration"]
    return {
        "sort": r["sort"],
        "custNo": r["custNo"] or "",
        "invoice": r["invoice"] or "",
        "companyName": r["companyName"],
        "industry": _category(r["industry"], "industry"),
        "companyScale": _company_scale(r["companyScale"]) or "",
        "jobName": r["jobName"],
        "workArea": _category(r["workArea"], "workArea"),
        "jobType": job_type,
        "jobCat": _category(r["jobCat"], "jobCat"),
        "duration": {
            "startYear": duration["startYear"],
            "startMonth": _select(duration["startMonth"], "startMonth"),
            "endYear": duration["endYear"],
            "endMonth": _select(duration["endMonth"], "endMonth", optional=True),
        },
        "description": r["description"],
        "skill": [{"text": x["text"], "value": x["value"]} for x in r["skill"]],
        "management": _select(r["management"], "management", optional=True),
        "salary": {
            "monthPay": salary["monthPay"] if job_type in SALARIED_JOB_TYPES else "",
            "yearPay": salary["yearPay"] if job_type in SALARIED_JOB_TYPES else "",
            "jobParttimeType": (
                _select(salary["jobParttimeType"], "jobParttimeType", optional=True)
                if job_type == PART_TIME_JOB_TYPE else ""
            ),
            "jobParttimePay": (
                salary["jobParttimePay"] if job_type == PART_TIME_JOB_TYPE else ""
            ),
        },
        "companyVisibility": r["companyVisibility"],
        "stillWork": r["stillWork"],
        "salaryVisibility": int(r["salaryVisibility"]),
    }


def experience_operation_body(
    document: dict, action: str, *,
    changes: dict | None = None, position: int | None = None,
) -> dict:
    if action not in ("create", "update", "delete"):
        raise UnsupportedWrite("Unsupported 104 EXPERIENCE action")
    records = experience_list(document)
    if action == "delete":
        if changes is not None or isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= len(records):
            raise UnsupportedWrite("104 EXPERIENCE delete needs existing sort")
        return {"blockValueList": {"experience": {"experiences": {"sort": [position]}}}}
    if not isinstance(changes, dict) or not changes or set(changes) - EDITABLE_FIELDS:
        raise UnsupportedWrite("104 EXPERIENCE unknown/empty fields")
    if action == "create":
        if position is not None or set(changes) != EDITABLE_FIELDS:
            raise UnsupportedWrite("104 EXPERIENCE create needs all editable native fields")
        # Real 104 POST of companyVisibility=False persisted as True.
        # This alters the user's privacy choice and leaves a record visible
        # even when post-write verification raises. Fail BEFORE submission.
        # True was independently verified in a reversible live POST cycle.
        if changes.get("companyVisibility") is not True:
            raise UnsupportedWrite(
                "104 EXPERIENCE create with companyVisibility=False is "
                "not verified: upstream persisted True; refusing unsafe write"
            )
        row = {**changes, "logo": "", "sort": len(records) + 1}
    else:
        if isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= len(records):
            raise UnsupportedWrite("104 EXPERIENCE update needs existing sort")
        current = next(record for record in records if record["sort"] == position)
        row = {**current, **changes}
    wire = experience_wire_record(row)
    if action == "create":
        wire.pop("sort")  # f30d uses undefined when creating a record
    theme = _select(document["experience"]["formData"]["themeChoose"]["selectedTheme"], "selectedTheme")
    return {"blockValueList": {"experience": {
        "experiences": [wire], "themeChoose": {"selectedTheme": theme},
    }}}


def _comparable(row: dict) -> dict:
    value = experience_wire_record(row)
    value.pop("sort", None)
    return value


def verify_experience_operation(
    before: dict, after: dict, action: str, *,
    body: dict, position: int | None,
) -> bool:
    """Verify exactly one record changed despite 104's descending GET order.

    Non-record metadata must be unchanged. Create has a new positive sort
    number, while delete may renumber rows. For delete compare a multiset
    of record payloads without their position numbers.
    """
    from collections import Counter
    import json

    old = experience_list(before)
    new = experience_list(after)
    old_form = before["experience"]["formData"]
    new_form = after["experience"]["formData"]
    if (
        old_form["seniority"] != new_form["seniority"]
        or old_form["themeChoose"] != new_form["themeChoose"]
    ):
        return False

    def by_sort(rows: list[dict]) -> dict[int, dict]:
        return {row["sort"]: _comparable(row) for row in rows}

    def bag(rows: list[dict]) -> Counter[str]:
        return Counter(json.dumps(
            _comparable(row), ensure_ascii=False, sort_keys=True
        ) for row in rows)

    old_rows, new_rows = by_sort(old), by_sort(new)
    if action == "create":
        if len(new) != len(old) + 1 or not set(old_rows) < set(new_rows):
            return False
        if any(old_rows[k] != new_rows.get(k) for k in old_rows):
            return False
        added_keys = set(new_rows) - set(old_rows)
        if len(added_keys) != 1:
            return False
        expected = body["blockValueList"]["experience"]["experiences"][0]
        return new_rows[added_keys.pop()] == expected
    if action == "update":
        if len(new) != len(old) or set(old_rows) != set(new_rows):
            return False
        if any(old_rows[k] != new_rows[k] for k in old_rows if k != position):
            return False
        expected = body["blockValueList"]["experience"]["experiences"][0]
        return experience_wire_record(
            next(row for row in new if row["sort"] == position)
        ) == expected
    if action == "delete":
        if len(new) != len(old) - 1 or position not in old_rows:
            return False
        removed = next(row for row in old if row["sort"] == position)
        return bag(new) == bag([row for row in old if row is not removed])
    return False
