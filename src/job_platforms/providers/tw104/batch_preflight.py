"""Read-only, evidence-limited plan for the first operation of a 104 batch.

Later operations depend on current upstream state after preceding writes.
Never pretend that static shape validation proves later dynamic eligibility.
Only known source-mapped read/serializer methods are called; no HTTP write.
"""
from __future__ import annotations

from job_platforms.core.errors import ConflictError, UnsupportedWrite
from .batch_edit import _label, validate_batch_steps
from .education_records import education_operation_body
from .experience_records import experience_operation_body
from .language_records import (
    language_operation_body, language_lists, validate_language_capacity,
    validate_language_selectors,
)
from .layout_theme import theme_body
from .project_records import project_operation_body
from .record_sort import sort_body
from .referrer_records import referrer_operation_body
from .revision_guard import require_revision_match
from .skill_records import skill_operation_body
from .writers import checked_write_paths, changed_sections
from job_platforms.core.patch import JsonPatchOperation

BODIES = {
    "skill": skill_operation_body,
    "education": education_operation_body,
    "experience": experience_operation_body,
    "referrer": referrer_operation_body,
    "project": project_operation_body,
}


async def preview_native_batch(client, resume_id, steps, *, expected_timestamp):
    """Validate first step against a current GET; mark later ones deferred.

    Dynamic preflight is *not* a reservation; an external edit may occur
    immediately after this call. The actual batch must still use If-Match,
    target validators, read-back, and per-step conflict checks.
    """
    operations = validate_batch_steps(steps)
    version = client._version(resume_id)
    current = await client.get_resume(version)
    require_revision_match(current, expected_timestamp)
    initial = operations[0]
    mode = initial["type"]
    if mode == "record":
        section, action = initial["section"], initial["action"]
        changes, position = initial.get("changes"), initial.get("position")
        if section == "language":
            language_operation_body(
                current, initial["kind"], action,
                changes=changes, position=position,
            )
            if action == "create":
                fields = client._data(await client.transport.get_json(
                    "/profile/ajax/inputField"
                ))
                validate_language_capacity(
                    fields, initial["kind"],
                    len(language_lists(current)[initial["kind"]]),
                )
            if action != "delete":
                choices = client._data(await client.transport.get_json(
                    "/profile/ajax/options"
                ))
                validate_language_selectors(choices, initial["kind"], changes)
        else:
            options = None
            if section in ("referrer", "project") and action == "create":
                form = current.get(section, {}).get("formData")
                if not isinstance(form, dict):
                    raise UnsupportedWrite("104 native formData missing for batch preflight")
                if not form:
                    options = client._data(await client.transport.get_json(
                        "/profile/ajax/options"
                    ))
            kwargs = {"changes": changes, "position": position}
            if section in ("referrer", "project"):
                kwargs["options"] = options
            BODIES[section](current, action, **kwargs)
        total_requests = 1
    elif mode == "patch":
        plan, _ = await client.plan_edit(version, initial["operations"])
        if str(plan.base_timestamp) != str(expected_timestamp):
            raise ConflictError("104 PATCH changed while constructing batch preview")
        total_requests = len(changed_sections(checked_write_paths([
            JsonPatchOperation.from_dict(item) for item in initial["operations"]
        ])))
    elif mode == "theme":
        options = client._data(await client.transport.get_json(
            "/profile/ajax/options"
        ))
        theme_body(current, options, initial["section"], initial["selected_theme"])
        total_requests = 1
    else:
        sort_body(
            current, initial["section"], initial["from_position"],
            initial["to_position"], kind=initial.get("kind"),
        )
        total_requests = 1
    # No user-supplied values are returned. In particular, never return the
    # native request body, full resume document, or selector option catalogs.
    return {
        "resume_id": version,
        "resumeTimestamp": current["resumeTimestamp"],
        "persisted": False,
        "network_write_sent": False,
        "atomic": False,
        "all_steps_dynamically_verified": len(operations) == 1,
        "checked_first_step_write_request_upper_bound": total_requests,
        "steps": [
            {"label": _label(step, index), "status": (
                "eligible_on_current_snapshot" if index == 1
                else "deferred_pending_prior_steps"
            )}
            for index, step in enumerate(operations, 1)
        ],
        "current_site_write_success_verified": False,
    }
