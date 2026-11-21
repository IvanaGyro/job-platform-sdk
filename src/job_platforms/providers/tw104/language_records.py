"""104 LANGUAGE local/foreign record CRUD with duplicate-type protection.

104 Vuex module 96e2: local and foreign are independent arrays, with
different selectors and delete/sort payloads. A real foreign POST with
an already-present type overwrote its existing row (not a CREATE).
Reject duplicate same-kind type creates before HTTP. Certificate associations
are separately managed; linked records are blocked until verified.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite


KINDS = ("foreign", "local")
FIELDS = {
    "foreign": frozenset(("type", "listening", "speaking", "reading", "writing", "certificate", "sort")),
    "local": frozenset(("type", "level", "sort")),
}
EDITABLE = {
    "foreign": FIELDS["foreign"] - {"sort", "certificate"},
    "local": FIELDS["local"] - {"sort"},
}


def _selected(value: Any, field: str) -> str | int:
    if not isinstance(value, dict) or not {"text", "value"} <= value.keys():
        raise UnsupportedWrite(f"104 LANGUAGE {field} requires selector")
    selected = value["value"]
    if isinstance(selected, bool) or not isinstance(selected, (int, str)) or selected == "":
        raise UnsupportedWrite(f"104 LANGUAGE {field} has invalid value")
    return selected


def _option_id(selector: Any, field: str) -> int:
    """Canonical native integer selector ID; reject ambiguous coercions."""
    raw = _selected(selector, field)
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isascii() and raw.isdecimal() and raw[0] != "0":
        return int(raw)
    raise UnsupportedWrite(f"104 LANGUAGE {field} must be a positive option ID")


def _type_id(selector: Any) -> int:
    return _option_id(selector, "type")


# Extracted from official editor `language-editor` component options bindings.
# `optionsLanguageType` is the UI foreign/dialect category, NOT a record ID.
LANGUAGE_SELECTOR_OPTIONS = {
    "foreign": {
        "type": "optionsForeignType",
        "listening": "optionsLanguageForeignLevel",
        "speaking": "optionsLanguageForeignLevel",
        "reading": "optionsLanguageForeignLevel",
        "writing": "optionsLanguageForeignLevel",
    },
    "local": {
        "type": "optionsLocalType",
        "level": "optionsLanguageLocalLevel",
    },
}


def validate_language_selectors(options: dict, kind: str, changes: dict) -> None:
    """Fail closed on unlisted or mislabeled selections before HTTP writes.

    Read options live from /profile/ajax/options, not from a baked-in catalog;
    a language's numeric value is scoped to its own foreign/local list.
    """
    if not isinstance(options, dict) or kind not in LANGUAGE_SELECTOR_OPTIONS:
        raise UnsupportedWrite("104 LANGUAGE options unavailable")
    for field, selector in changes.items():
        option_key = LANGUAGE_SELECTOR_OPTIONS[kind].get(field)
        entries = options.get(option_key) if option_key else None
        if not isinstance(entries, list):
            raise UnsupportedWrite(f"104 LANGUAGE {field} option catalog missing")
        value = _option_id(selector, field)
        if not isinstance(selector.get("text"), str):
            raise UnsupportedWrite(f"104 LANGUAGE {field} text missing")
        matching = [entry for entry in entries if isinstance(entry, dict)
                    and type(entry.get("value")) is int
                    and entry["value"] == value]
        if (len(matching) != 1 or matching[0].get("text") != selector["text"]):
            raise UnsupportedWrite(
                f"104 LANGUAGE {field} selector does not match current site options"
            )


def language_capacity_limit(fields: dict, kind: str) -> int:
    """Read a native maximum from the official editor inputField contract."""
    if kind not in KINDS or not isinstance(fields, dict):
        raise UnsupportedWrite("104 LANGUAGE inputField missing or invalid kind")
    section = fields.get("language")
    entry = section.get(kind) if isinstance(section, dict) else None
    maximum = entry.get("count") if isinstance(entry, dict) else None
    if type(maximum) is not int or maximum < 1:
        raise UnsupportedWrite("104 LANGUAGE current capacity unavailable")
    return maximum


def validate_language_capacity(fields: dict, kind: str, existing_count: int) -> None:
    """Check the native editor's current per-kind record-count constraint.

    Source: `language-editor` computes languageMaximum using the `foreign`
    and `local` `.count` values in GET /profile/ajax/inputField. Only
    CREATE increases count; UPDATE/DELETE never use this preflight.
    """
    if type(existing_count) is not int or existing_count < 0:
        raise UnsupportedWrite("104 LANGUAGE capacity check invalid")
    maximum = language_capacity_limit(fields, kind)
    if existing_count >= maximum:
        raise UnsupportedWrite("104 LANGUAGE current kind reached site record limit")


def language_editor_choices(options: dict, kind: str) -> dict[str, list[dict]]:
    """List current native choices without guessing or exposing raw backend JSON.

    All lists are source-mapped in the deployed language-editor component. A
    malformed/ambiguous option catalog fails closed (rather than dropping a
    duplicate option and allowing callers to write against a guessed ID).
    """
    if kind not in LANGUAGE_SELECTOR_OPTIONS or not isinstance(options, dict):
        raise UnsupportedWrite("104 LANGUAGE options missing")
    result = {}
    for field, source in LANGUAGE_SELECTOR_OPTIONS[kind].items():
        entries = options.get(source)
        if not isinstance(entries, list) or not entries:
            raise UnsupportedWrite(f"104 LANGUAGE {source} list unavailable")
        selected = []
        ids = set()
        for item in entries:
            if not isinstance(item, dict):
                raise UnsupportedWrite(f"104 LANGUAGE {source} malformed option")
            value = _option_id(item, field)
            label = item.get("text")
            if not isinstance(label, str) or not label.strip() or value in ids:
                raise UnsupportedWrite(f"104 LANGUAGE {source} duplicate or invalid option")
            ids.add(value)
            selected.append({"text": label, "value": value})
        result[field] = selected
    return result


def _record(row: Any, kind: str) -> dict:
    if kind not in KINDS:
        raise UnsupportedWrite("104 LANGUAGE kind must be local or foreign")
    if not isinstance(row, dict) or set(row) != FIELDS[kind]:
        raise UnsupportedWrite("104 LANGUAGE native record shape unsupported")
    if isinstance(row["sort"], bool) or not isinstance(row["sort"], int) or row["sort"] < 1:
        raise UnsupportedWrite("104 LANGUAGE sort invalid")
    for name in EDITABLE[kind]:
        _selected(row[name], name)
    if kind == "foreign":
        cert = row["certificate"]
        if not isinstance(cert, list):
            raise UnsupportedWrite("104 LANGUAGE certificate association changed")
    return deepcopy(row)


def language_lists(document: dict) -> dict[str, list[dict]]:
    try:
        form = document["language"]["formData"]
        data = form["languages"]
        theme = form["themeChoose"]["selectedTheme"]
    except (TypeError, KeyError) as exc:
        raise UnsupportedWrite("104 LANGUAGE native form missing") from exc
    _selected(theme, "selectedTheme")
    if not isinstance(data, dict) or not all(
        isinstance(data.get(kind), list) for kind in KINDS
    ):
        raise UnsupportedWrite("104 LANGUAGE collections missing")
    records = {kind: sorted((_record(x, kind) for x in data[kind]),
                            key=lambda row: row["sort"]) for kind in KINDS}
    for kind, rows in records.items():
        # GET array order is not guaranteed to be the numeric sort order.
        # The native DELETE/UPDATE contract identifies records by sort (not
        # by raw array position), so normalize only a unique contiguous set.
        if [row["sort"] for row in rows] != list(range(1, len(rows) + 1)):
            raise UnsupportedWrite(f"104 LANGUAGE {kind} sort identifiers not contiguous")
        # The deployed UI uses per-kind language IDs as distinct identities
        # during INSERT. When GET itself contains duplicate IDs, neither a
        # position-only UPDATE nor a new CREATE has safe identity semantics.
        ids = [_type_id(row["type"]) for row in rows]
        if len(ids) != len(set(ids)):
            raise UnsupportedWrite(f"104 LANGUAGE {kind} contains duplicate IDs")
    return records


def _wire(row: dict, kind: str, *, include_sort: bool) -> dict:
    _record(row, kind)
    # All source-mapped LANGUAGE native option IDs are numeric, including
    # proficiency selectors, so do not serialize string IDs as string values.
    result = {key: _option_id(row[key], key) for key in EDITABLE[kind]}
    if include_sort:
        result["sort"] = row["sort"]
    return result


def language_operation_body(
    document: dict, kind: str, action: str, *,
    changes: dict | None = None, position: int | None = None,
) -> dict:
    if kind not in KINDS or action not in ("create", "update", "delete"):
        raise UnsupportedWrite("104 LANGUAGE kind/action not supported")
    records = language_lists(document)
    existing = records[kind]
    if action == "delete":
        if changes is not None or isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= len(existing):
            raise UnsupportedWrite("104 LANGUAGE delete requires current record position")
        if kind == "foreign" and existing[position - 1]["certificate"]:
            raise UnsupportedWrite("104 LANGUAGE linked certificates require separate handling")
        buckets = {"foreign": {"sort": []}, "local": {"sort": []}}
        buckets[kind] = {"sort": [position]}
        return {"blockValueList": {"language": {"languages": buckets}}}
    if not isinstance(changes, dict) or not changes or set(changes) - EDITABLE[kind]:
        raise UnsupportedWrite("104 LANGUAGE changes contain invalid fields")
    if action == "create":
        if position is not None or set(changes) != EDITABLE[kind]:
            raise UnsupportedWrite("104 LANGUAGE create requires every selector")
        # On real 104, a FOREIGN POST with an existing type overwrote the
        # original foreign record instead of appending a second one.
        # `optionsLanguageType` selects the UI category (foreign/dialect);
        # each row's `type` selects an actual language within that category.
        # 104 can overwrite an existing row when a POST reuses its language ID.
        target_type = _type_id(changes["type"])
        if any(_type_id(item["type"]) == target_type for item in existing):
            raise UnsupportedWrite(
                "104 LANGUAGE create with existing type may overwrite "
                "the current record; use update instead"
            )
        row = {
            **changes, "sort": len(existing) + 1,
            **({"certificate": []} if kind == "foreign" else {}),
        }
    else:
        if isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= len(existing):
            raise UnsupportedWrite("104 LANGUAGE update requires current record position")
        if kind == "foreign" and existing[position - 1]["certificate"]:
            raise UnsupportedWrite("104 LANGUAGE linked certificates require separate handling")
        if "type" in changes:
            # PUT by sort with another existing language ID might be treated
            # upstream as an update to that other language. Reject on overlap.
            requested_id = _type_id(changes["type"])
            if any(_type_id(item["type"]) == requested_id
                   for idx, item in enumerate(existing, start=1) if idx != position):
                raise UnsupportedWrite(
                    "104 LANGUAGE update type would collide with another record"
                )
            if requested_id != _type_id(existing[position - 1]["type"]):
                # The official UI's type-changing edit can DELETE the old
                # record as a distinct request. This SDK deliberately issues
                # one request per operation, so a rename cannot be treated as
                # an ordinary in-place UPDATE until the exact lifecycle is
                # mapped and independently restored on the test resume.
                raise UnsupportedWrite(
                    "104 LANGUAGE changing a record's language type is unverified"
                )
        row = {**existing[position - 1], **changes}
    record = _wire(row, kind, include_sort=(action == "update"))
    buckets = {"foreign": [], "local": []}
    buckets[kind] = [record]
    selected_theme = _selected(
        document["language"]["formData"]["themeChoose"]["selectedTheme"],
        "selectedTheme",
    )
    return {"blockValueList": {"language": {
        "languages": buckets,
        "themeChoose": {"selectedTheme": selected_theme},
    }}}


def verify_language_operation(
    before: dict, after: dict, kind: str, action: str, *,
    body: dict, position: int | None,
) -> bool:
    old = language_lists(before)
    new = language_lists(after)
    # Protect every non-record field, including unknown future metadata. An
    # unrelated change must never count as a verified LANGUAGE mutation.
    old_form = before["language"]["formData"]
    new_form = after["language"]["formData"]
    if ({k: v for k, v in old_form.items() if k != "languages"}
            != {k: v for k, v in new_form.items() if k != "languages"}):
        return False
    other = "local" if kind == "foreign" else "foreign"
    if old[other] != new[other]:
        return False
    originals, current = old[kind], new[kind]
    def project(row):
        # Display text and certificate references are not part of the source
        # wire contract; *also* require associations to remain unchanged.
        return _wire(row, kind, include_sort=False)
    if action == "create":
        if len(current) != len(originals) + 1 or current[:-1] != originals:
            return False
        if kind == "foreign" and current[-1]["certificate"]:
            return False
        return project(current[-1]) == body["blockValueList"]["language"]["languages"][kind][0]
    if action == "update":
        if len(current) != len(originals):
            return False
        if any(current[i] != originals[i] for i in range(len(originals)) if i != position - 1):
            return False
        if kind == "foreign" and current[position - 1]["certificate"] != originals[position - 1]["certificate"]:
            return False
        return _wire(current[position - 1], kind, include_sort=True) == body["blockValueList"]["language"]["languages"][kind][0]
    if action == "delete":
        if len(current) != len(originals) - 1:
            return False
        expected = originals[:position - 1] + originals[position:]
        # DELETE renumbers the survivors' sort fields. Compare everything
        # else, especially FOREIGN certificate links; _wire/project would
        # silently omit those links and could report a destructive success.
        def without_sort(row: dict) -> dict:
            return {key: value for key, value in row.items() if key != "sort"}
        return ([without_sort(x) for x in current]
                == [without_sort(x) for x in expected])
    return False
