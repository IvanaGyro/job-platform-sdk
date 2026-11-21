"""Source-mapped 104 JOB_CONDITION write body, adapted from its frontend postData.

No cross-platform normalization: this encoder accepts the native formData
returned by the 104 resume editor. It rejects unknown shapes rather than
writing a partial object that could erase untouched preferences.

The official frontend uses PUT resumeByBlock/jobCondition with:
  blockValueList.jobCondition.jobCondition  (flattened selectors)
  blockValueList.jobCondition.themeChoose.selectedTheme (numeric theme)
This mapping is still experimental pending live read-after-write testing.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

# Explicitly keep new/unknown upstream form fields disabled until inspected.
NATIVE_FIELDS = frozenset((
    "jobTimeType", "jobWillType", "jobTimePeriod", "otherTimePeriod",
    "workShift", "onBoardDate", "onBoardAfterGetOffer",
    "customOnBoardDate", "salary", "salaryPeriod", "salaryOfHours",
    "salaryOfMonth", "salariesOfYear", "preferArea", "preferJobTitle",
    "preferJobType", "preferJobIndustry", "preferJobContent", "remoteWork",
))

# These nested fields are directly editable in the same form and use the
# identical source-observed jobCondition PUT encoder.
EDITABLE_FIELDS = NATIVE_FIELDS | frozenset((
    "preferJobTitle/text",
    "customOnBoardDate/year",
    "customOnBoardDate/month",
    "customOnBoardDate/date",
    "salaryOfMonth/unitOfTenThousand",
    "salaryOfMonth/unitOfThousand",
))
EDITABLE_PATHS = frozenset(
    "/jobCondition/formData/jobCondition/" + name for name in EDITABLE_FIELDS
)


def _require_object(value: Any, location: str) -> dict:
    if not isinstance(value, dict):
        raise UnsupportedWrite(f"104 JOB_CONDITION {location} must be an object")
    return value


def _value(item: Any, location: str) -> Any:
    if not isinstance(item, dict) or "value" not in item:
        raise UnsupportedWrite(f"104 JOB_CONDITION {location} must contain a value")
    value = item["value"]
    if isinstance(value, (dict, list)):
        raise UnsupportedWrite(f"104 JOB_CONDITION {location} value must be scalar")
    return value


def _select_list(items: Any, key: str) -> list[Any]:
    if not isinstance(items, list):
        raise UnsupportedWrite(f"104 JOB_CONDITION {key} must be an array")
    return [_value(item, key) for item in items]


def _no_list(items: Any, key: str) -> list[Any]:
    if not isinstance(items, list):
        raise UnsupportedWrite(f"104 JOB_CONDITION {key} must be an array")
    output = []
    for item in items:
        if not isinstance(item, dict) or "no" not in item:
            raise UnsupportedWrite(f"104 JOB_CONDITION {key} item requires no")
        no = item["no"]
        if isinstance(no, (list, dict)):
            raise UnsupportedWrite(f"104 JOB_CONDITION {key} no must be scalar")
        output.append(no)
    return output


def _source_empty(item: Any) -> bool:
    """Model the relevant lodash.isEmpty cases in the 104 frontend."""
    if item is None or isinstance(item, (bool, int, float)):
        return True
    return isinstance(item, (str, list, dict)) and not item


def _optional_value(item: Any, location: str) -> Any:
    if item is None or item == "" or item == {}:
        return ""
    # The GET view model uses selector objects. Reject a scalar accidentally
    # written by a caller: lodash.isEmpty(5) would otherwise silently clear it.
    return _value(item, location)


def native_job_condition(document: dict[str, Any]) -> dict[str, Any]:
    try:
        data = document["jobCondition"]["formData"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 JOB_CONDITION formData is unavailable") from exc
    if not isinstance(data, dict):
        raise UnsupportedWrite("104 JOB_CONDITION formData is not an object")
    native = _require_object(data.get("jobCondition"), "jobCondition")
    theme = _require_object(data.get("themeChoose"), "themeChoose")
    missing = NATIVE_FIELDS - native.keys()
    unknown = native.keys() - NATIVE_FIELDS
    if missing or unknown:
        raise UnsupportedWrite(
            "104 JOB_CONDITION native fields differ from the source-mapped contract"
        )
    _value(theme.get("selectedTheme"), "selectedTheme")
    return deepcopy({"jobCondition": native, "themeChoose": theme})


def job_condition_request_body(document: dict[str, Any]) -> dict[str, Any]:
    data = native_job_condition(document)
    value = data["jobCondition"]
    theme = data["themeChoose"]
    # Match the upstream frontend postData() conversion, not the GET model.
    out = deepcopy(value)
    for key in ("otherTimePeriod", "preferJobContent"):
        if not isinstance(value[key], str):
            raise UnsupportedWrite(f"104 JOB_CONDITION {key} must be a string")
    if (value["salaryOfHours"] is not None and
            (not isinstance(value["salaryOfHours"], (str, int, float))
             or isinstance(value["salaryOfHours"], bool))):
        raise UnsupportedWrite(
            "104 JOB_CONDITION salaryOfHours must be scalar or null"
        )
    for key in ("onBoardDate", "salary", "salaryPeriod"):
        out[key] = _value(value[key], key)
    for key in ("jobTimeType", "jobWillType", "jobTimePeriod"):
        out[key] = _select_list(value[key], key)
    for key in ("preferArea", "preferJobType", "preferJobIndustry"):
        out[key] = _no_list(value[key], key)

    date = _require_object(value["customOnBoardDate"], "customOnBoardDate")
    for key in ("year", "month", "date"):
        if key not in date:
            raise UnsupportedWrite(f"104 JOB_CONDITION customOnBoardDate missing {key}")
    if str(out["onBoardDate"]) not in ("1", "-1"):
        raise UnsupportedWrite("104 JOB_CONDITION unknown onboarding mode")
    if str(out["salary"]) not in ("1", "2", "3", "4"):
        raise UnsupportedWrite("104 JOB_CONDITION unknown salary mode")
    if str(out["onBoardDate"]) == "1":  # frontend constant onBoardAfterGetOffer
        out["onBoardAfterGetOffer"] = _optional_value(
            value["onBoardAfterGetOffer"], "onBoardAfterGetOffer"
        )
        out["customOnBoardDate"] = {"year": "", "month": "", "date": ""}
    else:
        out["onBoardAfterGetOffer"] = ""
        out["customOnBoardDate"] = {
            "year": "" if _source_empty(date["year"]) else date["year"],
            "month": _optional_value(date["month"], "customOnBoardDate.month"),
            "date": _optional_value(date["date"], "customOnBoardDate.date"),
        }

    if not isinstance(value["workShift"], (bool, int)):
        raise UnsupportedWrite("104 JOB_CONDITION workShift must be bool/int")
    if value["workShift"] not in (True, False, 0, 1):
        raise UnsupportedWrite("104 JOB_CONDITION workShift must be 0 or 1")
    out["workShift"] = 1 if value["workShift"] else 0
    month = _require_object(value["salaryOfMonth"], "salaryOfMonth")
    if not all(key in month for key in ("unitOfTenThousand", "unitOfThousand")):
        raise UnsupportedWrite("104 JOB_CONDITION salaryOfMonth is incomplete")
    if str(out["salary"]) == "4" and str(out["salaryPeriod"]) not in ("4", "5", "6"):
        raise UnsupportedWrite("104 JOB_CONDITION unknown custom salary period")
    if str(out["salary"]) == "4":  # frontend constant customSalary
        out["salary"] = out["salaryPeriod"]
        out["salaryOfMonth"] = {
            key: _optional_value(month[key], "salaryOfMonth." + key)
            for key in ("unitOfTenThousand", "unitOfThousand")
        }
        out["salariesOfYear"] = _optional_value(
            value["salariesOfYear"], "salariesOfYear"
        )
    else:
        out["salaryOfHours"] = ""
        out["salaryOfMonth"] = {
            "unitOfTenThousand": "", "unitOfThousand": ""
        }
        out["salariesOfYear"] = ""
    out["remoteWork"] = (
        0 if value["remoteWork"] is None or value["remoteWork"] == "" or value["remoteWork"] == {}
        else _value(value["remoteWork"], "remoteWork")
    )
    title = value["preferJobTitle"]
    # Real 104 GET 2026-11-17 returns a native string here, while
    # frontend editable view may wrap the title in {text: ...}.
    # Both normalize to a string in postData.
    if isinstance(title, str):
        out["preferJobTitle"] = title
    else:
        title = _require_object(title, "preferJobTitle")
        if not isinstance(title.get("text"), str):
            raise UnsupportedWrite("104 JOB_CONDITION preferJobTitle.text must be a string")
        out["preferJobTitle"] = title["text"]
    return {
        "blockValueList": {
            "jobCondition": {
                "jobCondition": out,
                "themeChoose": {
                    "selectedTheme": _value(theme["selectedTheme"], "selectedTheme")
                },
            }
        }
    }
