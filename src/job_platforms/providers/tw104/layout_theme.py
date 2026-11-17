"""104 per-section theme change through the separate LAYOUT PUT.

Frontend actions use /profile/ajax/resumeByBlock/layout, not the section's own
PUT. Valid themes come from the site's current /profile/ajax/options response
rather than guessed numerical ranges. Source-mapped, not live-write verified.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

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
    # Changing a theme must not silently replace any unrelated resume blocks.
    for name in THEME_OPTION_KEYS:
        if name != section and name in before and name in after:
            if before[name] != after[name]:
                return False
    return True
