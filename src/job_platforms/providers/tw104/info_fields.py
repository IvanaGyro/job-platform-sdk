"""Source-mapped 104 INFO form writer (selected native resume fields only).

Reference: 104 editor c40f.postData(), 33a0 info theme defaults.
Identity/contact fields absent from this serializer (birth date, login phone,
job status etc.) are NOT writable here, even if present in GET. Media uploads
are deliberately excluded. No real 104 write verification yet.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

BASE_FIELDS = frozenset({
    "military", "honoraryDischargeYear", "honoraryDischargeMonth",
    "city", "street", "bio", "motto", "trait",
    "personalLink1Type", "personalLink1Url", "personalLink2Type",
    "personalLink2Url", "personalLink3Type", "personalLink3Url",
})
ADDON_FIELDS = frozenset({
    "tel", "telArea", "contact", "englishName", "subCellphone",
    "driveCert", "trafficTool", "height", "weight", "marriageStatus",
    "specialRole", "nationality", "dis1Type", "dis1Level",
    "dis2Type", "dis2Level", "dis3Type", "dis3Level",
    "disManual", "disTool", "disDesc",
})
INFO_PATHS = frozenset({
    *(f"/info/formData/info/{name}" for name in BASE_FIELDS),
    *(f"/info/formData/addOn/{name}" for name in ADDON_FIELDS),
    *(f"/info/formData/summaryDisplay",),
})
HONORARY_DATE_MILITARY_VALUES = frozenset({1, 2})  # 33a0.needHonoraryDateArray
INFO_THEME_DEFAULT_COLORS = {
    1: "", 2: "", 3: "", 4: "#eddfcd", 5: "#566876",
    6: "#dbdbd5", 7: "#ffffff", 8: "#000000",
    9: "", 10: "#ffffff",
}


def _text(value: Any, field: str, *, nullable: bool = False) -> str | int | None:
    if nullable and value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise UnsupportedWrite(f"104 INFO {field} must be text/int")
    return value


def _selected(value: Any, field: str, *, optional: bool = False) -> str | int:
    if optional and value in (None, {}, "", []):
        return ""
    if not isinstance(value, dict) or "value" not in value:
        raise UnsupportedWrite(f"104 INFO {field} must have selector value")
    return _text(value["value"], field)


def _values(data: Any, field: str) -> list[str | int]:
    if not isinstance(data, list):
        raise UnsupportedWrite(f"104 INFO {field} must be an array")
    return [_selected(x, field) for x in data]


def _no_list(data: Any, field: str) -> list[str | int]:
    if not isinstance(data, list):
        raise UnsupportedWrite(f"104 INFO {field} must be an array")
    if not all(isinstance(x, dict) and "no" in x for x in data):
        raise UnsupportedWrite(f"104 INFO {field} category shape changed")
    return [_text(x["no"], field) for x in data]


def native_info_data(doc: dict) -> dict:
    """Read the editable INFO form while preserving all native fields."""
    try:
        form = doc["info"]["formData"]
        base, addon = form["info"], form["addOn"]
        theme, summary = form["themeChoose"], form["summaryDisplay"]
    except (TypeError, KeyError) as exc:
        raise UnsupportedWrite("104 INFO native form is unavailable") from exc
    if not isinstance(base, dict) or not isinstance(addon, dict):
        raise UnsupportedWrite("104 INFO native info/addOn must be objects")
    if not isinstance(theme, dict) or not isinstance(summary, list):
        raise UnsupportedWrite("104 INFO missing theme/summary")
    return deepcopy({
        "info": base, "addOn": addon,
        "themeChoose": theme, "summaryDisplay": summary,
    })


def info_request_body(doc: dict) -> dict:
    """Mirror c40f.postData with explicit omission of undefined optional keys."""
    form = native_info_data(doc)
    base, addon = form["info"], form["addOn"]
    # Require the entire source-observed request input: missing data must
    # not be silently converted to empty values and overwrite remote state.
    required = BASE_FIELDS - {"honoraryDischargeMonth", "honoraryDischargeYear"}
    if not required <= base.keys():
        raise UnsupportedWrite("104 INFO required base source fields missing")
    required_addon = ADDON_FIELDS - {"height", "weight", "marriageStatus"}
    if not required_addon <= addon.keys():
        raise UnsupportedWrite("104 INFO required addon source fields missing")

    military = _selected(base["military"], "military", optional=True)
    honorary = str(military) in {"1", "2"}
    city = _no_list(base["city"], "city")
    if len(city) != 1:
        raise UnsupportedWrite("104 INFO requires exactly one selected city")
    trait = base["trait"]
    if not isinstance(trait, list) or not all(
        isinstance(item, dict) and "text" in item and
        isinstance(item["text"], str) for item in trait
    ):
        raise UnsupportedWrite("104 INFO invalid trait entries")
    outgoing_base = {
        "military": military,
        "honoraryDischargeYear": (
            _text(base.get("honoraryDischargeYear", ""), "honoraryDischargeYear")
            if honorary else ""
        ),
        "honoraryDischargeMonth": (
            _selected(base.get("honoraryDischargeMonth"), "honoraryDischargeMonth", optional=True)
            if honorary else ""
        ),
        "city": city[0],
        "street": _text(base["street"], "street"),
        "bio": _text(base["bio"], "bio"),
        "motto": _text(base["motto"], "motto"),
        "trait": [{"text": x["text"], "value": "0"} for x in trait],
    }
    for i in (1, 2, 3):
        url_key = f"personalLink{i}Url"
        type_key = f"personalLink{i}Type"
        url = _text(base[url_key], url_key)
        outgoing_base[url_key] = url
        outgoing_base[type_key] = _selected(
            base[type_key], type_key, optional=not bool(url),
        ) if url else ""

    outgoing_addon = {
        key: _text(addon[key], key)
        for key in ("tel", "telArea", "contact", "englishName", "subCellphone")
    }
    for key in ("driveCert", "trafficTool", "specialRole", "disTool"):
        outgoing_addon[key] = _values(addon[key], key)
    outgoing_addon["nationality"] = _no_list(addon["nationality"], "nationality")
    for key in (
        "marriageStatus", "dis1Type", "dis1Level",
        "dis2Type", "dis2Level", "dis3Type", "dis3Level", "disManual",
    ):
        if key in addon:
            outgoing_addon[key] = _selected(addon[key], key, optional=True)
    for key in ("height", "weight", "disDesc"):
        if key in addon:
            outgoing_addon[key] = _text(addon[key], key, nullable=True)

    theme = form["themeChoose"]
    selected = _selected(theme.get("selectedTheme"), "selectedTheme")
    if isinstance(selected, str) or selected not in INFO_THEME_DEFAULT_COLORS:
        raise UnsupportedWrite("104 INFO theme has unexpected value")
    color = theme.get("backgroundColor")
    if not isinstance(color, str):
        raise UnsupportedWrite("104 INFO theme background missing")
    # c40f.postData uses a default color for certain visual themes. 104 may
    # rewrite display metadata on unrelated INFO writes; reject absent
    # colors rather than unintentionally switching the layout.
    if not color and INFO_THEME_DEFAULT_COLORS[selected]:
        raise UnsupportedWrite("104 INFO colored theme needs explicit background")
    summary = _values(form["summaryDisplay"], "summaryDisplay")
    return {"blockValueList": {"info": {
        "info": outgoing_base,
        "addon": outgoing_addon,
        "themeChoose": {
            "selectedTheme": {"value": selected}, "backgroundColor": color,
        },
        "summaryDisplay": summary,
    }}}
