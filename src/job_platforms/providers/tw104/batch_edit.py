"""Bounded, non-atomic sequence of existing 104 native SDK writes.

No guessed endpoints. Every step runs an already implemented writer with
its own version guard and target/collateral read-back verification.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from job_platforms.core.errors import (
    ConflictError, PartialWriteError, UnsupportedWrite, VerificationError,
)
from job_platforms.core.patch import JsonPatchOperation
from .layout_theme import THEME_OPTION_KEYS
from .record_sort import SORTABLE
from .patch_verification import (
    PRESERVE_BLOCKS, stable_block_equal, verify_untouched_blocks,
)
from .revision_guard import require_revision_match
from .writers import checked_write_paths, changed_sections

MAX_STEPS = 12
RECORD_SECTIONS = frozenset({
    "skill", "education", "experience", "referrer", "project", "language",
})


def _position(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 10000


def _keys(step: dict, required: set, optional=frozenset()):
    if not required <= step.keys() or set(step) - required - optional:
        raise UnsupportedWrite("104 batch step has missing or unsupported fields")


def validate_batch_steps(steps: Any) -> list[dict]:
    """Validate *all* step structure before credentials or remote writes.

    Site-specific field/capacity checks occur in individual writers using
    new GETs, since earlier steps may have changed later records and slots.
    """
    if type(steps) is not list or not 1 <= len(steps) <= MAX_STEPS:
        raise UnsupportedWrite("104 batch requires 1 to 12 ordered operations")
    verified = []
    for step in steps:
        if type(step) is not dict or type(step.get("type")) is not str:
            raise UnsupportedWrite("104 batch operation requires object and type")
        mode = step["type"]
        if mode == "record":
            _keys(step, {"type", "section", "action"}, {"position", "kind", "changes"})
            section, action = step["section"], step["action"]
            if type(section) is not str or section not in RECORD_SECTIONS or action not in (
                "create", "update", "delete",
            ):
                raise UnsupportedWrite("104 batch record section/action unsupported")
            if section == "language":
                if step.get("kind") not in ("local", "foreign"):
                    raise UnsupportedWrite("104 batch language kind required")
            elif "kind" in step:
                raise UnsupportedWrite("104 batch kind only applies to language")
            if action == "create":
                if "position" in step:
                    raise UnsupportedWrite("104 batch create cannot specify sort")
            elif not _position(step.get("position")):
                raise UnsupportedWrite("104 batch update/delete needs positive sort")
            if action != "delete":
                if type(step.get("changes")) is not dict or not step["changes"]:
                    raise UnsupportedWrite("104 batch create/update needs changed fields")
            elif "changes" in step:
                raise UnsupportedWrite("104 batch delete takes no changes")
        elif mode == "patch":
            _keys(step, {"type", "operations"})
            ops = step["operations"]
            if type(ops) is not list or not 1 <= len(ops) <= 64:
                raise UnsupportedWrite("104 batch PATCH requires 1-64 operations")
            try:
                parsed = [JsonPatchOperation.from_dict(item) for item in ops]
                if not checked_write_paths(parsed):
                    raise UnsupportedWrite("104 batch PATCH must contain supported writes")
            except (TypeError, KeyError, ValueError, IndexError):
                raise UnsupportedWrite("104 batch PATCH shape unsupported") from None
        elif mode == "theme":
            _keys(step, {"type", "section", "selected_theme"})
            if (type(step["section"]) is not str or step["section"] not in THEME_OPTION_KEYS
                    or not _position(step["selected_theme"])):
                raise UnsupportedWrite("104 batch theme selection invalid")
        elif mode == "sort":
            _keys(step, {"type", "section", "from_position", "to_position"}, {"kind"})
            if (type(step["section"]) is not str or step["section"] not in SORTABLE
                    or not _position(step["from_position"])
                    or not _position(step["to_position"])
                    or step["from_position"] == step["to_position"]):
                raise UnsupportedWrite("104 batch sort section/positions invalid")
            if step["section"] == "language":
                if step.get("kind") not in ("local", "foreign"):
                    raise UnsupportedWrite("104 batch LANGUAGE sort kind missing")
            elif "kind" in step:
                raise UnsupportedWrite("104 batch sort kind only for language")
        else:
            raise UnsupportedWrite("104 batch step type unsupported")
        verified.append(deepcopy(step))
    return verified


def _label(step: dict, index: int) -> str:
    # Do not include record names, field paths, values or arbitrary user text.
    if step["type"] == "record":
        return f"{index}:{step['section']}.{step['action']}"
    return f"{index}:{step['type']}"

async def apply_native_batch(client, resume_id: str | int, steps: list[dict], *,
                             expected_timestamp: str | int) -> dict:
    """Sequence individual verified writers; never retry or rollback.

    First-step errors propagate; after one success, a later failure becomes
    PartialWriteError with step labels only, not private field values.
    """
    operations = validate_batch_steps(steps)
    version = client._version(resume_id)
    previous = await client.get_resume(version)
    require_revision_match(previous, expected_timestamp)
    completed: list[str] = []
    for number, step in enumerate(operations, 1):
        label = _label(step, number)
        try:
            if number > 1:
                fresh = await client.get_resume(version)
                require_revision_match(fresh, client._edit_timestamp(previous))
                if not all(stable_block_equal(previous, fresh, section)
                           for section in PRESERVE_BLOCKS):
                    raise ConflictError("104 resume changed between batch steps")
                previous = fresh
            stamp = client._edit_timestamp(previous)
            if step["type"] == "record":
                section = step["section"]
                method = getattr(client, f"mutate_{section}")
                args = (version, step["action"]) if section != "language" else (
                    version, step["kind"], step["action"]
                )
                kwargs = {"expected_timestamp": stamp}
                for field in ("position", "changes"):
                    if field in step:
                        kwargs[field] = step[field]
                result = await method(*args, **kwargs)
            elif step["type"] == "patch":
                plan, _ = await client.plan_edit(version, step["operations"])
                if str(plan.base_timestamp) != str(stamp):
                    raise ConflictError("104 resume changed before batch PATCH")
                result = await client.save_edit(plan)
            elif step["type"] == "theme":
                result = await client.set_theme(
                    version, step["section"], step["selected_theme"],
                    expected_timestamp=stamp,
                )
            else:
                result = await client.sort_records(
                    version, step["section"], step["from_position"],
                    step["to_position"], expected_timestamp=stamp,
                    **({"kind": step["kind"]} if "kind" in step else {}),
                )
            if (not isinstance(result, dict) or result.get("verified") is not True
                    or result.get("persisted") is not True):
                raise VerificationError("104 batch step has no verified persisted change")
            after = await client.get_resume(version)
            client._edit_timestamp(after)
            # The SDK writer performed its own read-back, but an external
            # editor could change another section before this batch captures
            # its next baseline. Do not silently adopt such collateral edits.
            if step["type"] == "patch":
                touched = tuple(changed_sections(checked_write_paths([
                    JsonPatchOperation.from_dict(op) for op in step["operations"]
                ])))
            else:
                touched = step["section"]
            if not verify_untouched_blocks(previous, after, changed=touched):
                raise VerificationError("104 batch post-step snapshot changed unexpectedly")
            previous = after
            completed.append(label)
        except Exception:
            if completed:
                raise PartialWriteError(completed, label) from None
            raise
    return {
        "resume_id": version, "verified": True, "persisted": True,
        "atomic": False, "verified_steps": completed, "step_count": len(completed),
    }
