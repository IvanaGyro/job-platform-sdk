"""104 PORTFOLIO native deletion and record listing.

The editor module 44aa creates new attachments using multipart/form-data
(and optional asynchronous preview generation). This module deliberately
does NOT attempt that upload. DELETE uses the current sort value with the
native structure blockValueList.portfolio.sort=[N]. Sorting is handled
separately using swapRecordBySort.

GET shape for populated PORTFOLIO was checked against a real *read-only*
104 response. Writes have NOT been tested on a real resume.
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


def portfolio_delete_body(doc: dict, *, position: int) -> dict:
    rows = portfolio_records(doc)
    if (
        isinstance(position, bool) or not isinstance(position, int)
        or position not in {row["sort"] for row in rows}
    ):
        raise UnsupportedWrite("104 PORTFOLIO delete requires an existing sort")
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

    def without_sort(row: dict) -> dict:
        return {key: deepcopy(value) for key, value in row.items() if key != "sort"}

    target = next((r for r in old if r["sort"] == position), None)
    if target is None:
        return False
    expected = [without_sort(r) for r in old if r["sort"] != position]
    actual = [without_sort(r) for r in new]
    # Preserve relative order even when site reassigns sort numbers.
    return actual == expected


def portfolio_link_fields(
    doc: dict, changes: dict, *, options: dict | None = None,
) -> dict[str, str]:
    """Source-map frontend 44aa's multipart LINK=2 insertion, no file bytes.

    Attachment-file uploads, thumbnail conversion and modification remain
    separate, unimplemented operations.
    """
    from urllib.parse import urlsplit

    records = portfolio_records(doc)
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
    form = doc["portfolio"]["formData"]
    if form:
        theme = form["themeChoose"]["selectedTheme"]["value"]
    else:
        themes = options.get("optionsPortfolioTheme") if isinstance(options, dict) else None
        if not isinstance(themes, list) or not themes:
            raise UnsupportedWrite("104 PORTFOLIO first link needs current site themes")
        entry = themes[0]
        if not isinstance(entry, dict):
            raise UnsupportedWrite("104 PORTFOLIO initial theme invalid")
        theme = entry.get("value")
    if isinstance(theme, bool) or not isinstance(theme, int) or theme < 1:
        raise UnsupportedWrite("104 PORTFOLIO theme value invalid")
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
    from collections import Counter
    import json
    def bag(rows):
        return Counter(json.dumps(
            {k: v for k, v in row.items() if k != "sort"},
            ensure_ascii=False, sort_keys=True,
        ) for row in rows)
    added = bag(new) - bag(old)
    if sum(added.values()) != 1:
        return False
    added_signature = next(iter(added))
    added_record = next(
        (row for row in new if json.dumps(
            {k: v for k, v in row.items() if k != "sort"},
            ensure_ascii=False, sort_keys=True,
        ) == added_signature),
        None,
    )
    if added_record is None:
        return False
    attach = added_record["attach"]
    return (
        added_record["name"] == fields["blockValueList[portfolio][name]"]
        and str(added_record["attachType"]["value"]) == "2"
        and attach["name"] == fields["blockValueList[portfolio][attach][name]"]
        and attach["url"] == fields["blockValueList[portfolio][attach][url]"]
    )
