"""104 CUSTOM source-mapped text-only native request *planner*.

104 front-end Vuex custom module 4228 postData() and theme constants
5255 (TEXT=3) define the payload below. Unlike the other native
writers, CUSTOM uses dynamically numbered slots custom1..custom6 and
a real populated GET was observed on an authorized test resume
2026-11-17. The TEXT=3 one-record POST/PUT/DELETE lifecycle was
independently verified and restored, including a second
live Python SDK wrapper create/update/delete test. Other themes and media remain
unimplemented.

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

    Caller must verify that the target slot is currently absent
    and that the native version has not changed before network POST.
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
    """Source-observed one-slot DELETE, live-verified for only custom1."""
    number = _slot(slot)
    return {"blockValueList": {
        "custom": {"custom": {"sort": [number]}},
    }}


def custom_text_update_body(
    existing: dict, *, name: str | None = None,
    introduction_html: str | None = None,
) -> dict:
    """Plan text-only PUT from an exact, caller-owned GET form.

    Reject unknown media/additional content before reconstructing the
    site-native text-only payload. This path passed a real live PUT.
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
    duration = row["duration"]
    if (
        not isinstance(duration, dict)
        or not {"startYear", "startMonth", "endYear", "endMonth"} <= duration.keys()
        or set(duration) - {
            "startYear", "startMonth", "endYear", "endMonth",
            "index", "durationGroup",
        }
        or any(duration.get(k) not in (None, "", {})
               for k in ("startYear", "startMonth", "endYear", "endMonth"))
        or duration.get("index", -1) not in (-1, None)
        or duration.get("durationGroup", {}) not in ({}, None)
    ):
        raise UnsupportedWrite("104 CUSTOM text has unsupported date information")
    for key, value in media[0].items():
        if key == "type":
            continue
        if key not in {
            "url", "src", "fileId", "thumbnailStatus", "thumbnailUrl", "content", "ext",
        } or value not in (None, ""):
            raise UnsupportedWrite("104 CUSTOM text has unexpected media metadata")
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

def custom_text_form(doc: dict, *, slot: int) -> dict | None:
    """Extract the real populated TEXT=3 native GET and fail closed.

    Native GET materializes new CUSTOM as customN rather than a
    top-level custom section. Tested formData contains:
    custom:{name,sort,content:[...]}, themeChoose.selectedTheme object.
    """
    number=_slot(slot)
    try:
        section=doc.get(f"custom{number}")
        if section is None:
            return None
        if not isinstance(section,dict):
            raise UnsupportedWrite("104 CUSTOM section type changed")
        form=section["formData"]
        # No-op title patch validates native media, dates and text.
        custom_text_update_body(form,name=form["custom"]["name"])
        if form["custom"]["sort"]!=number:
            raise UnsupportedWrite("104 CUSTOM native slot mismatch")
        return deepcopy(form)
    except (KeyError,TypeError,IndexError):
        raise UnsupportedWrite("104 CUSTOM populated form shape changed") from None


def verify_custom_text_mutation(
    before: dict, after: dict, action: str, *, slot: int,
    body: dict,
) -> bool:
    """Verify TEXT fields and preservation of all other CUSTOM slots."""
    number=_slot(slot)
    target=f"custom{number}"
    slots={f"custom{n}" for n in range(1,7)}
    old_set={k for k in before if k in slots}
    new_set={k for k in after if k in slots}
    for k in old_set | new_set:
        if k != target and before.get(k) != after.get(k):
            return False
    if action=="delete":
        return target in old_set and target not in new_set
    if action=="create" and (
        target in old_set or new_set != old_set | {target}
    ):
        return False
    if action=="update" and (target not in old_set or target not in new_set):
        return False
    try:
        current=custom_text_form(after,slot=number)
    except UnsupportedWrite:
        return False
    if current is None:
        return False
    expected=body["blockValueList"]["custom"]
    item=current["custom"]
    desired=expected["custom"]
    if (
        item["name"]!=desired["name"]
        or item["sort"]!=desired["sort"]
        or current["themeChoose"]["selectedTheme"]["value"]!=TEXT_THEME
        or len(item["content"])!=1
    ):
        return False
    row=item["content"][0]
    return row["introduction"]==desired["content"][0]["introduction"]
