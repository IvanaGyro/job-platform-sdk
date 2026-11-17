"""104 CUSTOM source-mapped text-only native request *planner*.

104 front-end Vuex custom module 4228 postData() and theme constants
5255 (TEXT=3) define the payload below. Unlike the other native
writers, CUSTOM uses dynamically numbered slots custom1..custom6 and
the actual populated GET/read-back contract has not been observed.
Consequently this module deliberately only serializes/validates
requests. No SDK mutation, HTTP write, or CLI write is enabled.

The official UI creates a content item with duration, isInProgress,
introduction, url, and file. For TEXT theme postData() normalizes
file to type NONE=0, removes UI-only duration.index/durationGroup,
and converts the selectedTheme option into its numeric value. We
support exactly one text-only content entry and no media uploads.
"""
from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

TEXT_THEME = 3
SLOT_MIN, SLOT_MAX = 1, 6
NO_MEDIA = {"type": 0, "content": "", "ext": ""}

class _TextTagParser(HTMLParser):
    """Reject risky markup; this is a conservative text-only adapter."""
    ALLOWED = {"p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li"}
    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED or attrs:
            raise UnsupportedWrite("104 CUSTOM plain text has unsafe markup")
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        if tag not in self.ALLOWED:
            raise UnsupportedWrite("104 CUSTOM plain text has unsafe markup")
    def handle_entityref(self, name):
        if name not in {"amp", "lt", "gt", "quot", "apos", "nbsp"}:
            raise UnsupportedWrite("104 CUSTOM unsupported HTML entity")


def _slot(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (
        SLOT_MIN <= value <= SLOT_MAX
    ):
        raise UnsupportedWrite("104 CUSTOM slot must be custom1 through custom6")
    return value


def _safe_text(value: Any, label: str, max_len: int, *, required: bool) -> str:
    if not isinstance(value, str) or len(value) > max_len or (
        required and not value.strip()
    ):
        raise UnsupportedWrite(f"104 CUSTOM {label} text invalid")
    return value


def _safe_html(html: Any) -> str:
    raw = _safe_text(html, "introduction", 4000, required=True)
    parser = _TextTagParser(convert_charrefs=True)
    try:
        parser.feed(raw)
        parser.close()
    except (ValueError, TypeError):
        raise UnsupportedWrite("104 CUSTOM invalid introduction HTML") from None
    return raw


def custom_text_create_body(
    *, slot: int, name: str, introduction_html: str,
    theme_options: dict,
) -> dict:
    """Exact text-only outgoing POST shape from 4228.postData().

    No account/remote state is read here, so callers MUST NOT send
    this body before separately verifying that the custom slot is
    available, the session version is current, and a fresh GET has
    a known read-back schema.
    """
    number = _slot(slot)
    label = _safe_text(name, "name", 30, required=True)
    html = _safe_html(introduction_html)
    choices = (
        theme_options.get("optionsCustomTheme")
        if isinstance(theme_options, dict) else None
    )
    if not isinstance(choices, list) or not any(
        isinstance(x, dict) and type(x.get("value")) is int
        and x.get("value") == TEXT_THEME for x in choices
    ):
        raise UnsupportedWrite("104 CUSTOM text theme unavailable in site options")
    return {"blockValueList": {"custom": {
        "custom": {
            "name": label, "sort": number,
            "content": [{
                "duration": {
                    "startYear": "", "startMonth": "",
                    "endYear": "", "endMonth": "",
                },
                "isInProgress": 0,
                "introduction": html,
                "url": "",
                "file": [deepcopy(NO_MEDIA)],
            }],
        },
        "themeChoose": {"selectedTheme": TEXT_THEME},
    }}}


def custom_delete_body(*, slot: int) -> dict:
    """Source-observed one-slot DELETE, no network call."""
    number = _slot(slot)
    return {"blockValueList": {
        "custom": {"custom": {"sort": [number]}},
    }}


def custom_text_update_body(
    existing: dict, *, name: str | None = None,
    introduction_html: str | None = None,
) -> dict:
    """Plan text-only PUT from an exact, caller-owned GET form.

    This rejects any unknown media or additional content instead of
    overwriting it with NONE. It is a serializer, not a remote write.
    """
    if name is None and introduction_html is None:
        raise UnsupportedWrite("104 CUSTOM update needs at least one change")
    if not isinstance(existing, dict) or set(existing) != {
        "custom", "themeChoose",
    }:
        raise UnsupportedWrite("104 CUSTOM populated form unverified")
    custom, theme = existing["custom"], existing["themeChoose"]
    if (
        not isinstance(custom, dict)
        or set(custom) != {"name", "sort", "content"}
        or not isinstance(theme, dict)
        or not isinstance(theme.get("selectedTheme"), dict)
        or theme["selectedTheme"].get("value") != TEXT_THEME
    ):
        raise UnsupportedWrite("104 CUSTOM record/theme shape unsupported")
    number = _slot(custom["sort"])
    rows = custom["content"]
    if not isinstance(rows, list) or len(rows) != 1:
        raise UnsupportedWrite("104 CUSTOM text update accepts one content only")
    row=rows[0]
    if not isinstance(row, dict) or set(row) != {
        "duration", "isInProgress", "introduction", "url", "file",
    }:
        raise UnsupportedWrite("104 CUSTOM content fields unverified")
    media=row["file"]
    if not isinstance(media, list) or len(media) != 1 or not isinstance(
        media[0], dict
    ) or media[0].get("type") != 0:
        raise UnsupportedWrite("104 CUSTOM record has media; refusing overwrite")
    if not isinstance(row["duration"], dict) or any(
        row["duration"].get(k) not in (None, "", {})
        for k in ("startYear", "startMonth", "endYear", "endMonth")
    ):
        raise UnsupportedWrite("104 CUSTOM text has unsupported date information")
    if row["isInProgress"] not in (False, 0, []):
        raise UnsupportedWrite("104 CUSTOM text has unsupported progress state")
    if row["url"] not in ("", None):
        raise UnsupportedWrite("104 CUSTOM text URL not supported")
    if name is None:
        name = custom["name"]
    if introduction_html is None:
        introduction_html = row["introduction"]
    if not isinstance(name,str) or not isinstance(introduction_html,str):
        raise UnsupportedWrite("104 CUSTOM original text fields unsupported")
    # Reuse the same canonical wire structure; static theme is known
    # from the existing GET and does not require querying site options.
    return custom_text_create_body(
        slot=number, name=name, introduction_html=introduction_html,
        theme_options={"optionsCustomTheme": [{"value": TEXT_THEME}]},
    )
