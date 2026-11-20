"""Non-transactional 104 JSON Patch read-after-write preservation checks.

A target value being correct does not establish that its parent record or
other resume sections survived a PUT. The only known stable-GET exception
is the four rotating opaque access fields on PORTFOLIO FILE attachments.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite
from .layout_theme import _same_portfolio_ignoring_file_access_tokens
from .writers import section_data, sidebar_records

# These are the source-observed editable native blocks in a resumeByBlock GET.
# Snapshot comparison is strict for all but FILE attachment access tokens.
PRESERVE_BLOCKS = (
    "info", "education", "experience", "jobCondition", "skill",
    "certificate", "language", "project", "portfolio", "bio",
    "referrer", "sidebar", "under18",
    *(f"custom{i}" for i in range(1, 7)),
)


def stable_block_equal(before: dict, after: dict, block: str) -> bool:
    """Compare an entire non-target section, with one proven volatile case."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if (block in before) != (block in after):
        return False
    if block not in before:
        return True
    if before[block] == after[block]:
        return True
    if block != "portfolio":
        return False
    return _same_portfolio_ignoring_file_access_tokens(
        before[block], after[block],
    )


def _strip_target_data(document: dict[str, Any], section: str) -> dict:
    """Remove only fields whose change was verified by section_data()."""
    native = deepcopy(document[section])
    form = native["formData"]
    if section == "experience":
        # Seniority PUT changes its label along with its numeric value.
        # Keep *all* experiences and all other form/section metadata intact.
        del form["seniority"]
    elif section == "bio":
        # section_data verifies BOTH chi and eng, even for a one-field PATCH.
        del form["bio"]
    elif section == "certificate":
        cert = form["certificate"]
        del cert["others"]
        # Native GET may use `certifications` with no `certificates` key.
        # The latter is a writer field; the former must not change unnoticed.
        cert.pop("certificates", None)
    else:
        raise UnsupportedWrite("No partial-section verification for this writer")
    return native


def _same_sidebar_records(before: dict, after: dict) -> bool:
    old = sidebar_records(before)
    new = sidebar_records(after)
    if len(old) != len(new):
        return False
    def map_by_id(rows):
        return {(type(row["id"]).__name__, row["id"]): row for row in rows}
    return map_by_id(old) == map_by_id(new)


def verify_patch_transition(
    before: dict, after: dict, section: str, desired_section: Any,
) -> bool:
    """Require the expected write *and* preservation of unmodified data.

    Compare against the newest pre-PUT GET, not the initial edit-plan GET,
    because earlier verified blocks in a multi-section save intentionally
    changed. Never make a retry decision from a failed/ambiguous check.
    """
    if section not in PRESERVE_BLOCKS or not isinstance(after, dict):
        return False
    try:
        if section_data(after, section) != desired_section:
            return False
        for sibling in PRESERVE_BLOCKS:
            if sibling != section and not stable_block_equal(before, after, sibling):
                return False
        if section == "sidebar":
            return _same_sidebar_records(before, after)
        if section in ("bio", "certificate", "experience"):
            return _strip_target_data(before, section) == _strip_target_data(after, section)
        # INFO and JOB_CONDITION section_data already include all known
        # editable native form fields and theme data. Their serializer read-
        # back contract is deliberately not broadened to volatile view props.
        return True
    except (UnsupportedWrite, KeyError, TypeError, ValueError, AttributeError):
        return False
