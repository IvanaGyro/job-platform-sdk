"""104 per-section theme change through the separate LAYOUT PUT.

Frontend actions use /profile/ajax/resumeByBlock/layout, not the section's own
PUT. Valid themes come from the site's current /profile/ajax/options response
rather than guessed numerical ranges. JOB_CONDITION theme PUT and exact
restoration were live-verified through BrowserTransport. Other sections
remain source-mapped and experimental.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite
from .portfolio_records import portfolio_records

# Observed on two consecutive, unmodified 104 GETs in a single login:
# FILE attachment URLs and opaque file identifiers are regenerated.
# This list is deliberately much narrower than an entire PORTFOLIO record.
VOLATILE_FILE_FIELDS = frozenset((
    "fileId", "src", "thumbnailFileId", "url",
))


def _same_portfolio_ignoring_file_access_tokens(old: dict, new: dict) -> bool:
    """Compare every stable portfolio field; LINK URLs are NOT ignored.

    Only FILE=1 has regenerated URL/opaque file token fields on real 104.
    Refuse missing data, changed record identities, metadata or unknown shapes.
    """
    try:
        old_rows = portfolio_records({"portfolio": old})
        new_rows = portfolio_records({"portfolio": new})
    except (UnsupportedWrite, TypeError, KeyError, ValueError):
        return False
    if len(old_rows) != len(new_rows):
        return False
    lhs, rhs = deepcopy(old), deepcopy(new)
    left_form, right_form = lhs["formData"], rhs["formData"]
    if not left_form or not right_form:
        return lhs == rhs
    for a, b in zip(left_form["portfolios"], right_form["portfolios"]):
        # The 104 LINK=2 destination is user content, not a volatile token.
        atype = a["attachType"]["value"]
        btype = b["attachType"]["value"]
        if str(atype) != str(btype):
            return False
        if str(atype) == "1":  # FILE only
            for name in VOLATILE_FILE_FIELDS:
                a["attach"].pop(name, None)
                b["attach"].pop(name, None)
    return lhs == rhs


THEME_OPTION_KEYS = {
    "info": "optionsInfoTheme",
    "education": "optionsEducationTheme",
    "experience": "optionsExperienceTheme",
    "jobCondition": "optionsJobConditionTheme",
    "skill": "optionsSkillTheme",
    "certificate": "optionsCertificateTheme",
    "language": "optionsLanguageTheme",
    "project": "optionsProjectTheme",
    "portfolio": "optionsPortfolioTheme",
    "referrer": "optionsReferrerTheme",
    "custom": "optionsCustomTheme",
}


def allowed_theme_values(options: dict, section: str) -> set[int]:
    key = THEME_OPTION_KEYS.get(section)
    if not key or not isinstance(options, dict):
        raise UnsupportedWrite("104 theme section or options are unsupported")
    entries = options.get(key)
    if not isinstance(entries, list) or not entries:
        raise UnsupportedWrite("104 theme list not provided by site")
    allowed = set()
    for value in entries:
        if not isinstance(value, dict) or "value" not in value:
            raise UnsupportedWrite("104 theme option shape changed")
        option = value["value"]
        if isinstance(option, bool) or not isinstance(option, int) or option < 1 or option in allowed:
            raise UnsupportedWrite("104 theme option value invalid")
        allowed.add(option)
    return allowed


def native_theme(document: dict, section: str) -> int:
    if section not in THEME_OPTION_KEYS:
        raise UnsupportedWrite("104 theme section unsupported")
    try:
        theme = document[section]["formData"]["themeChoose"]["selectedTheme"]
        selected = theme["value"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 section does not contain native theme") from exc
    if isinstance(selected, bool) or not isinstance(selected, int) or selected < 1:
        raise UnsupportedWrite("104 native theme selector invalid")
    return selected


def theme_body(document: dict, options: dict, section: str, selected_theme: int) -> dict:
    if isinstance(selected_theme, bool) or not isinstance(selected_theme, int):
        raise UnsupportedWrite("104 theme must be a numeric selector")
    native_theme(document, section)
    if selected_theme not in allowed_theme_values(options, section):
        raise UnsupportedWrite("104 theme not included in current site options")
    return {"blockValueList": {
        "layout": {"themeChoose": {"block": section, "selectedTheme": selected_theme}}
    }}


def verify_theme_write(before: dict, after: dict, section: str, selected_theme: int) -> bool:
    if native_theme(after, section) != selected_theme:
        return False
    old = deepcopy(before[section])
    new = deepcopy(after[section])
    # The site's readable title/name for the selected theme changes as well.
    for block in (old, new):
        del block["formData"]["themeChoose"]["selectedTheme"]
    if old != new:
        return False
    # Keep unrelated editable blocks equal. A real no-op double GET showed
    # FILE-only opaque access token and signed URL rotation in PORTFOLIO.
    # Treat only that narrow case as equivalent; never ignore LINK URLs or
    # a change to names, sort order, visibility or non-portfolio sections.
    for name in THEME_OPTION_KEYS:
        if name == section:
            continue
        if (name in before) != (name in after):
            return False
        if name not in before:
            continue
        if before[name] != after[name]:
            if name != "portfolio" or not _same_portfolio_ignoring_file_access_tokens(
                before[name], after[name]
            ):
                return False
    return True
