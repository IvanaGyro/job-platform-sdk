"""104 native adjacent record move via swapRecordBySort.

Source actions (Vuex a41b, 8ea9) send {"sort":{"from":A,"to":B}}.
We only allow *adjacent* moves until non-adjacent upstream semantics
(swap versus insertion) have been live verified. Adjacent moves have
identical effects under both interpretations.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite
from .education_records import education_list
from .skill_records import skill_list

SORTABLE = {"education": "educations", "skill": "skills"}


def _records(doc: dict, section: str) -> list:
    if section == "education":
        return education_list(doc)
    if section == "skill":
        return skill_list(doc)
    raise UnsupportedWrite("104 sortable section not source-mapped")


def sort_body(doc: dict, section: str, from_position: int, to_position: int) -> dict:
    records = _records(doc, section)
    if (
        any(isinstance(x, bool) or not isinstance(x, int) for x in (from_position, to_position))
        or not 1 <= from_position <= len(records)
        or not 1 <= to_position <= len(records)
        or abs(from_position - to_position) != 1
    ):
        raise UnsupportedWrite("104 sort supports only adjacent 1-based positions")
    # Identical records cannot give an independent read-back confirmation.
    left = {k: v for k, v in records[from_position - 1].items() if k != "sort"}
    right = {k: v for k, v in records[to_position - 1].items() if k != "sort"}
    if left == right:
        raise UnsupportedWrite("104 sort of indistinguishable records is unverifiable")
    return {"blockValueList": {section: {
        SORTABLE[section]: {"sort": {"from": from_position, "to": to_position}}
    }}}


def verify_sort(before: dict, after: dict, section: str, from_position: int, to_position: int) -> bool:
    """All non-sort data must equal exactly the expected adjacent permutation."""
    old = _records(before, section)
    new = _records(after, section)
    if len(old) != len(new):
        return False
    def strip(row: dict) -> dict:
        return {k: deepcopy(v) for k, v in row.items() if k != "sort"}
    expected = [strip(item) for item in old]
    expected[from_position - 1], expected[to_position - 1] = (
        expected[to_position - 1], expected[from_position - 1]
    )
    if [strip(item) for item in new] != expected:
        return False
    # The record reorder must not alter theme or any other section fields.
    for name in (section,):
        old_form = before[name]["formData"]
        new_form = after[name]["formData"]
        for field in old_form:
            if field != SORTABLE[section] and old_form[field] != new_form.get(field):
                return False
    return True
