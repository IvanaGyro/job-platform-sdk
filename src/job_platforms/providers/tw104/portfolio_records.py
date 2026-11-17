"""104 PORTFOLIO native deletion and record listing.

The editor module 44aa creates new attachments using multipart/form-data.
The SDK now source-maps LINK=2 (text fields) and FILE=1
(PDF/PNG/JPEG with an in-memory multipart File), while asynchronous
conversion/preview handling remains unimplemented. FILE upload is
synthetic-tested only, not live-validated. DELETE uses the current sort value with the
native structure blockValueList.portfolio.sort=[N]. Sorting is handled
separately using swapRecordBySort.

GET shape for populated PORTFOLIO was checked against a real *read-only*
104 response. FILE/LINK writes have NOT been tested on a real resume.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

FIELDS = frozenset({"name", "attach", "attachType", "sort"})


def portfolio_record(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise UnsupportedWrite("104 PORTFOLIO record shape changed")
    if (not isinstance(value["name"], str) or not value["name"].strip()
            or len(value["name"]) > 120):
        raise UnsupportedWrite("104 PORTFOLIO attachment name required")
    attach = value["attach"]
    if not isinstance(attach, dict) or set(attach) != {
        "name", "status", "url", "fileId", "thumbnailFileId",
        "src", "crawler",
    }:
        raise UnsupportedWrite("104 PORTFOLIO attach shape has changed")
    if any(not isinstance(attach[k], str) for k in (
        "name", "url", "fileId", "thumbnailFileId", "src"
    )) or not isinstance(attach["status"], int) or not isinstance(attach["crawler"], bool):
        raise UnsupportedWrite("104 PORTFOLIO attach field types unsupported")
    typ = value["attachType"]
    if not isinstance(typ, dict) or "value" not in typ or isinstance(
        typ["value"], bool
    ) or not isinstance(typ["value"], (int, str)):
        raise UnsupportedWrite("104 PORTFOLIO attachType selector changed")
    pos = value["sort"]
    if isinstance(pos, bool) or not isinstance(pos, int) or pos < 1:
        raise UnsupportedWrite("104 PORTFOLIO sort must be positive")
    return deepcopy(value)


def portfolio_records(doc: dict) -> list[dict]:
    try:
        form = doc["portfolio"]["formData"]
    except (TypeError, KeyError) as exc:
        raise UnsupportedWrite("104 PORTFOLIO formData missing") from exc
    if not isinstance(form, dict):
        raise UnsupportedWrite("104 PORTFOLIO native form invalid")
    if not form:
        return []
    if set(form) != {"portfolios", "themeChoose"}:
        raise UnsupportedWrite("104 PORTFOLIO native form shape changed")
    theme = form["themeChoose"]
    if not isinstance(theme, dict) or not isinstance(theme.get("selectedTheme"), dict):
        raise UnsupportedWrite("104 PORTFOLIO selectedTheme missing")
    v = theme["selectedTheme"].get("value")
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise UnsupportedWrite("104 PORTFOLIO theme option invalid")
    entries = form["portfolios"]
    if not isinstance(entries, list):
        raise UnsupportedWrite("104 PORTFOLIO attachments must be a list")
    rows = [portfolio_record(x) for x in entries]
    if len(rows) > 6:
        raise UnsupportedWrite("104 PORTFOLIO exceeds supported site count")
    sorts = [x["sort"] for x in rows]
    forward = list(range(1, len(rows) + 1))
    if sorts != forward and sorts != forward[::-1]:
        raise UnsupportedWrite("104 PORTFOLIO records have unsafe sort IDs")
    return rows


def portfolio_stable_identity(row: dict) -> tuple[str, str, int, str | None]:
    """Identify a displayed item without opaque expiring attachment URLs.

    The real 104 FILE=1 GET includes large opaque fileId,
    thumbnailFileId, src and url strings. These are not guaranteed
    persistent across separately authenticated sessions. Do NOT
    mistake a changed expiring access token for a replaced attachment.

    Display name, attachment filename and type are stable UI fields.
    For LINK=2, its destination URL is also part of the identity.
    This is a best-effort identity for *same-session* verification only;
    it is not a global immutable file identifier.
    """
    item = portfolio_record(row)
    raw = item["attachType"]["value"]
    if type(raw) is int and raw in (1, 2):
        kind = raw
    elif type(raw) is str and raw in ("1", "2"):
        kind = int(raw)
    else:
        raise UnsupportedWrite("104 PORTFOLIO attachType not a known FILE/LINK")
    return (
        item["name"],
        item["attach"]["name"],
        kind,
        item["attach"]["url"] if kind == 2 else None,
    )


def portfolio_stable_identities(doc: dict) -> list[tuple]:
    """Ordered identities; reject ambiguous duplicate file names."""
    identities = [portfolio_stable_identity(x) for x in portfolio_records(doc)]
    if len(set(identities)) != len(identities):
        raise UnsupportedWrite(
            "104 PORTFOLIO has indistinguishable displayed attachments"
        )
    return identities


def portfolio_delete_body(doc: dict, *, position: int) -> dict:
    rows = portfolio_records(doc)
    if (
        isinstance(position, bool) or not isinstance(position, int)
        or position not in {row["sort"] for row in rows}
    ):
        raise UnsupportedWrite("104 PORTFOLIO delete requires an existing sort")
    portfolio_stable_identities(doc)
    # Note: unlike PROJECT, the site uses portfolio.sort directly.
    return {"blockValueList": {"portfolio": {"sort": [position]}}}


def verify_portfolio_delete(
    before: dict, after: dict, *, position: int,
) -> bool:
    old = portfolio_records(before)
    new = portfolio_records(after)
    if len(new) != len(old) - 1:
        return False
    old_theme = before["portfolio"]["formData"].get("themeChoose")
    new_theme = after["portfolio"]["formData"].get("themeChoose")
    if new_theme is not None and old_theme != new_theme:
        return False
    try:
        identities = portfolio_stable_identities(before)
        resulting = portfolio_stable_identities(after)
    except (UnsupportedWrite, ValueError):
        return False
    chosen = next((i for i, row in enumerate(old) if row["sort"] == position), None)
    return (
        chosen is not None
        and resulting == [x for i, x in enumerate(identities) if i != chosen]
    )


def _new_portfolio_theme(doc: dict, options: dict | None) -> int:
    form = doc["portfolio"]["formData"]
    if form:
        theme = form["themeChoose"]["selectedTheme"]["value"]
    else:
        themes = options.get("optionsPortfolioTheme") if isinstance(options, dict) else None
        if not isinstance(themes, list) or not themes:
            raise UnsupportedWrite("104 PORTFOLIO needs current site themes")
        entry = themes[0]
        if not isinstance(entry, dict):
            raise UnsupportedWrite("104 PORTFOLIO first theme invalid")
        theme = entry.get("value")
    if type(theme) is not int or theme < 1:
        raise UnsupportedWrite("104 PORTFOLIO theme value invalid")
    return theme


def portfolio_file_fields(
    doc: dict, changes: dict, *, options: dict | None = None,
) -> dict[str, str]:
    """Site 44aa.CREATE FILE=1 multipart fields, excluding binary bytes.

    The browser must add 'attachment' as an actual File object.
    Preview generation is separate and not yet verified on the real site.
    """
    rows = portfolio_records(doc)
    portfolio_stable_identities(doc)
    if len(rows) >= 6:
        raise UnsupportedWrite("104 PORTFOLIO maximum file count reached")
    if not isinstance(changes, dict) or set(changes) != {"name", "attachName"}:
        raise UnsupportedWrite("104 PORTFOLIO file requires name and attachName")
    for field in ("name", "attachName"):
        value = changes[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise UnsupportedWrite("104 PORTFOLIO invalid file display name")
    theme = _new_portfolio_theme(doc, options)
    return {
        "blockValueList[portfolio][themeChoose][selectedTheme]": str(theme),
        "blockValueList[portfolio][name]": changes["name"],
        "blockValueList[portfolio][attachType]": "1",
        "blockValueList[portfolio][attach][name]": changes["attachName"],
        "blockValueList[portfolio][attach][src]": "",
    }


def verify_portfolio_file_create(
    before: dict, after: dict, *, fields: dict[str, str],
) -> bool:
    original = portfolio_records(before)
    current = portfolio_records(after)
    if len(current) != len(original) + 1:
        return False
    old_form = before["portfolio"]["formData"]
    new_form = after["portfolio"]["formData"]
    if old_form and old_form["themeChoose"] != new_form.get("themeChoose"):
        return False
    try:
        previous = portfolio_stable_identities(before)
        updated = portfolio_stable_identities(after)
    except (UnsupportedWrite, TypeError, ValueError):
        return False
    expected = (
        fields["blockValueList[portfolio][name]"],
        fields["blockValueList[portfolio][attach][name]"],
        1, None,
    )
    if expected in previous or updated.count(expected) != 1:
        return False
    uploaded = next(x for x in current if portfolio_stable_identity(x) == expected)
    # File upload may still be pending async thumbnail generation, but
    # 104 must acknowledge an addressable file before persistence is
    # considered confirmed; an empty placeholder is not success.
    attach = uploaded["attach"]
    if not (attach["fileId"] or attach["url"]):
        return False
    updated.remove(expected)
    return updated == previous


def portfolio_link_fields(
    doc: dict, changes: dict, *, options: dict | None = None,
) -> dict[str, str]:
    """Source-map frontend 44aa's multipart LINK=2 insertion, no file bytes.

    Binary FILE=1 upload is a separate SDK method, not this LINK=2
    serializer; thumbnail conversion and modification remain unimplemented.
    """
    from urllib.parse import urlsplit

    records = portfolio_records(doc)
    portfolio_stable_identities(doc)
    if len(records) >= 6:
        raise UnsupportedWrite("104 PORTFOLIO has reached its maximum entry count")
    if not isinstance(changes, dict) or set(changes) != {
        "name", "attachName", "url",
    }:
        raise UnsupportedWrite("104 PORTFOLIO link requires name, attachName, url")
    name, attach_name, link = (
        changes["name"], changes["attachName"], changes["url"],
    )
    for field, value in (("name", name), ("attachName", attach_name)):
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise UnsupportedWrite(f"104 PORTFOLIO invalid link {field}")
    if not isinstance(link, str) or len(link) > 200:
        raise UnsupportedWrite("104 PORTFOLIO link URL too long")
    parsed = urlsplit(link)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise UnsupportedWrite("104 PORTFOLIO URL must be http(s)")
    theme = _new_portfolio_theme(doc, options)
    # 401c: FILE=1, LINK=2. 44aa.CREATE uses FormData, NOT JSON.
    # No Content-Type is set manually; the browser chooses its boundary.
    return {
        "blockValueList[portfolio][themeChoose][selectedTheme]": str(theme),
        "blockValueList[portfolio][name]": name,
        "blockValueList[portfolio][attachType]": "2",
        "blockValueList[portfolio][attach][name]": attach_name,
        "blockValueList[portfolio][attach][url]": link,
    }


def verify_portfolio_link_create(
    before: dict, after: dict, *, fields: dict[str, str],
) -> bool:
    old, new = portfolio_records(before), portfolio_records(after)
    if len(new) != len(old) + 1:
        return False
    old_form = before["portfolio"]["formData"]
    new_form = after["portfolio"]["formData"]
    if old_form and old_form["themeChoose"] != new_form.get("themeChoose"):
        return False
    try:
        original = portfolio_stable_identities(before)
        current = portfolio_stable_identities(after)
    except (UnsupportedWrite, ValueError):
        return False
    requested = (
        fields["blockValueList[portfolio][name]"],
        fields["blockValueList[portfolio][attach][name]"],
        2,
        fields["blockValueList[portfolio][attach][url]"],
    )
    if requested in original or current.count(requested) != 1:
        # Avoid claiming an inserted duplicate was individually identified.
        return False
    current.remove(requested)
    return current == original
