"""Privacy-preserving, read-only view of the deployed 104 inputField rules.

The legacy `/profile/ajax/inputField` route was read-only checked on the
2026-11-17 test resume. Its names correspond to official frontend
`inputField.data.<name>` bindings. This adapter never echoes unrecognized
strings, option lists, sensitive field values or full response JSON.
"""
from __future__ import annotations

import re
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

# Source-mapped against the deployed 104 Vue editor. Public API sections use
# singular names; the inputField catalog uses plural record group names.
INPUT_FIELD_GROUPS = {
    "info": "info", "bio": "bio", "education": "education",
    "experience": "experience", "jobCondition": "jobCondition",
    "skill": "skill", "certificate": "certificate",
    "language": "language", "project": "projects",
    "portfolio": "portfolios", "referrer": "referrers",
    "custom": "customs",
}

INTEGER_LIMIT_KEYS = frozenset({
    "count", "maxLength", "minLength", "htmlMaxLength", "max", "min",
    "maxValue", "minValue", "maxCount", "minCount",
})
BOOLEAN_LIMIT_KEYS = frozenset({"required"})
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}\Z")
MAX_DEPTH = 7
MAX_NODES = 1000


def _sanitize_rules(value: Any, *, depth: int, budget: list[int]) -> dict:
    if depth > MAX_DEPTH or not isinstance(value, dict):
        return {}
    if len(value) > MAX_NODES:
        raise UnsupportedWrite("104 editor limit catalog is unexpectedly large")
    result = {}
    for name, item in value.items():
        budget[0] -= 1
        if budget[0] < 0:
            raise UnsupportedWrite("104 editor limit catalog exceeds safe bounds")
        if not isinstance(name, str) or not _FIELD_NAME.fullmatch(name):
            continue
        if name in INTEGER_LIMIT_KEYS:
            if type(item) is int and 0 <= item <= 1_000_000:
                result[name] = item
        elif name in BOOLEAN_LIMIT_KEYS:
            if type(item) is bool:
                result[name] = item
        elif isinstance(item, dict):
            child = _sanitize_rules(item, depth=depth + 1, budget=budget)
            if child:
                result[name] = child
        # Deliberately omit strings (text, regex, explanations), arrays
        # (dynamic options/user data), and any unrecognized scalar values.
    return result


def native_editor_limits(payload: dict, section: str) -> dict:
    """Return known numeric/boolean limits without leaking response values.

    A missing/malformed group is not silently converted to unlimited fields.
    Empty rules are valid when no recognized numeric limit is available; the
    response then explicitly has `limits_available=False`.
    """
    source = INPUT_FIELD_GROUPS.get(section)
    if source is None:
        raise UnsupportedWrite("104 editor limit section unsupported")
    if not isinstance(payload, dict) or not isinstance(payload.get(source), dict):
        raise UnsupportedWrite("104 editor limit group missing")
    result = _sanitize_rules(payload[source], depth=0, budget=[MAX_NODES])
    return {
        "provider": "tw104", "section": section,
        "source": "/profile/ajax/inputField", "source_group": source,
        "constraints": result, "limits_available": bool(result),
        "persisted": False, "read_only": True,
        "scope": "numeric/boolean source constraints only; not proof of writable fields",
    }
