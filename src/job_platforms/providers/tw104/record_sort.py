"""104 adjacent record sorting through the native swapRecordBySort API.

Frontend actions a41b (SKILL), 8ea9 (EDUCATION), 96e2 (LANGUAGE),
1d22 (PROJECT), 44aa (PORTFOLIO), and f5d8 (REFERRER,
exactly 2 entries only; editor hardcodes from=2,to=1).
For LANGUAGE, its sortable groups are independent and the UI supplies
both foreign and local sort branches (the inactive branch contains []).
All sections except PORTFOLIO still support adjacent moves only.
PORTFOLIO 1-to-3 non-adjacent ordering was verified live on
2026-11-17 and follows insertion semantics: remove the source row
and insert at the destination, rather than exchanging endpoints.
"""
from __future__ import annotations

from copy import deepcopy

from job_platforms.core.errors import UnsupportedWrite

from .education_records import education_list
from .language_records import KINDS, language_lists
from .project_records import project_records
from .portfolio_records import portfolio_records, portfolio_stable_identities
from .skill_records import skill_list
from .referrer_records import referrer_records

SORTABLE = {
    "education": "educations", "skill": "skills",
    "language": "languages", "project": "projects",
    "portfolio": "portfolios", "referrer": "referrers",
}


def _records(doc: dict, section: str, kind: str | None) -> list:
    if section == "language":
        if kind not in KINDS:
            raise UnsupportedWrite("104 LANGUAGE sort requires kind local or foreign")
        return language_lists(doc)[kind]
    if kind is not None:
        raise UnsupportedWrite("104 sort kind is only supported for language")
    if section == "education":
        return education_list(doc)
    if section == "skill":
        return skill_list(doc)
    if section == "project":
        return project_records(doc)
    if section == "portfolio":
        return portfolio_records(doc)
    if section == "referrer":
        records = referrer_records(doc)
        # Official editor f5d8.SORT always sends from=2,to=1,
        # ignoring the proposed sort payload. Do NOT generalize to N>2.
        if len(records) != 2:
            raise UnsupportedWrite("104 REFERRER sort supported only for exactly 2 entries")
        return records
    raise UnsupportedWrite("104 sortable section not source-mapped")


def _without_sort(row: dict) -> dict:
    return {key: deepcopy(value) for key, value in row.items() if key != "sort"}


def sort_body(
    doc: dict, section: str, from_position: int, to_position: int, *,
    kind: str | None = None,
) -> dict:
    records = _records(doc, section, kind)
    if (
        isinstance(from_position, bool) or not isinstance(from_position, int)
        or isinstance(to_position, bool) or not isinstance(to_position, int)
        or not 1 <= from_position <= len(records)
        or not 1 <= to_position <= len(records)
        or from_position == to_position
        or (section != "portfolio" and abs(from_position - to_position) != 1)
    ):
        raise UnsupportedWrite(
            "104 sort supports only adjacent moves except PORTFOLIO insertion"
        )
    # Independent read-back cannot distinguish two otherwise identical rows.
    if section == "portfolio":
        # Signed fileId/url/preview tokens can rotate between native GETs.
        # Verify source-defined adjacent order by unique stable display ID.
        identities = portfolio_stable_identities(doc)
        if identities[from_position - 1] == identities[to_position - 1]:
            raise UnsupportedWrite("104 PORTFOLIO sort is ambiguous")
    elif _without_sort(records[from_position - 1]) == _without_sort(records[to_position - 1]):
        raise UnsupportedWrite("104 sort cannot verify indistinguishable records")
    move = (
        {"from": 2, "to": 1} if section == "referrer"
        else {"from": from_position, "to": to_position}
    )
    if section == "language":
        # 104 UI dragEnd() sends both buckets with an empty sort list in
        # the inactive language group, not a single group.
        return {"blockValueList": {"language": {"languages": {
            "foreign": {"sort": move if kind == "foreign" else []},
            "local": {"sort": move if kind == "local" else []},
        }}}}
    return {"blockValueList": {
        section: {SORTABLE[section]: {"sort": move}},
    }}


def verify_sort(
    before: dict, after: dict, section: str,
    from_position: int, to_position: int, *, kind: str | None = None,
) -> bool:
    """Require an exact adjacent permutation without changes to siblings."""
    old = _records(before, section, kind)
    new = _records(after, section, kind)
    if len(old) != len(new):
        return False
    if section == "portfolio":
        try:
            expected = portfolio_stable_identities(before)
            actual = portfolio_stable_identities(after)
        except (UnsupportedWrite, ValueError):
            return False
    else:
        expected = [_without_sort(row) for row in old]
        actual = [_without_sort(row) for row in new]
    if section == "portfolio":
        # A real 104 GET after 1->3 in a 3-item portfolio displayed
        # [B,C,A], not [C,B,A]. This is an insertion move.
        moved=expected.pop(from_position-1)
        expected.insert(to_position-1,moved)
    else:
        expected[from_position - 1], expected[to_position - 1] = (
            expected[to_position - 1], expected[from_position - 1]
        )
    if actual != expected:
        return False

    old_form = before[section]["formData"]
    new_form = after[section]["formData"]
    for field, value in old_form.items():
        if field != SORTABLE[section] and value != new_form.get(field):
            return False
    if section == "language":
        other = "local" if kind == "foreign" else "foreign"
        if language_lists(before)[other] != language_lists(after)[other]:
            return False
    return True
