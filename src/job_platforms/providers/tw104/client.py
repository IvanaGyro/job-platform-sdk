"""104 resume read, create and local multi-field editing.

Native 104 section writers are strict, versioned and verified by readback.
BIO PUT, PROJECT no-media CRUD and CERTIFICATE block lifecycle have
passed authenticated test-resume round trips. Other native operations
remain experimental or read-only, as documented by section.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from job_platforms.core.errors import (
    AuthenticationRequired, ConflictError, ResumeNotFound, UnsupportedWrite,
    VerificationError, PartialWriteError,
)
from job_platforms.core.patch import (
    EditPlan, JsonPatchOperation, apply_json_patch, describe_schema,
)
from .transport import BrowserTransport, BrowserUpload
from .skill_records import skill_list, skill_operation_body, verify_skill_operation
from .record_sort import SORTABLE, sort_body, verify_sort
from .layout_theme import (
    THEME_OPTION_KEYS, native_theme, theme_body, verify_theme_write,
)
from .language_records import (
    KINDS as LANGUAGE_KINDS, language_lists, language_operation_body,
    validate_language_selectors, validate_language_capacity,
    language_editor_choices, language_capacity_limit,
    verify_language_operation,
)
from .bio_actions import bio_action_body, verify_bio_action
from .certificate_block_actions import (
    certificate_block_body, verify_certificate_block,
)
from .certificate_connection_records import (
    dispatch_certification_action, validate_certificate_action,
    verify_certificate_association,
)
from .project_records import (
    project_records, project_operation_body, verify_project_operation,
)
from .portfolio_records import (
    portfolio_records, portfolio_delete_body, verify_portfolio_delete,
    portfolio_link_fields, verify_portfolio_link_create,
    portfolio_file_fields, verify_portfolio_file_create,
)
from .custom_text_contract import (
    custom_text_form, custom_text_create_body,
    custom_text_update_body, custom_delete_body,
    verify_custom_text_mutation,
)
from .custom_themes import custom_theme_capabilities
from .custom_layout_records import (
    LAYOUT_THEMES, layout_operation_body, verify_layout_mutation,
)
from .under18_records import under18_operation_body, verify_under18_operation
from .portfolio_preview import conversion_file_id,convert_status_summary
from .referrer_records import (
    referrer_records, referrer_operation_body, verify_referrer_operation,
)
from .experience_records import (
    experience_list, experience_operation_body, verify_experience_operation,
)
from .education_records import (
    education_list, education_operation_body, verify_education_operation,
)
from .editor_limits import INPUT_FIELD_GROUPS, native_editor_limits
from .revision_guard import is_revision, revision_matches, require_revision_match
from .batch_edit import apply_native_batch, validate_batch_steps
from .batch_preflight import preview_native_batch
from .patch_verification import (
    PRESERVE_BLOCKS, stable_block_equal, verify_patch_transition,
    verify_untouched_blocks,
)
from .writers import (
    checked_write_paths, changed_sections, section_data, section_request_body,
    validate_section_edit, patch_path_catalog,
)


class Resume104Client:
    # The editor dynamically registers up to six numbered custom slots.
    # This list is for reading and schema introspection only: unknown custom
    # fields remain explicitly blocked by native write path validation.
    CUSTOM_SLOTS = tuple(f"custom{n}" for n in range(1, 7))
    SECTIONS = (
        "info", "education", "experience", "jobCondition", "skill",
        "certificate", "language", "project", "portfolio", "bio",
        "referrer", "sidebar", "under18",
    ) + CUSTOM_SLOTS

    def __init__(self, page: Any = None, *, transport: Any = None):
        if page is None and transport is None:
            raise ValueError("104 requires a browser page or ready transport")
        self.page = page
        self.transport = transport if transport is not None else BrowserTransport(page)
        self._write_lock = asyncio.Lock()

    @staticmethod
    def _version(value: str | int) -> str:
        v = str(value)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v):
            raise ValueError("Invalid resume version")
        return v

    @staticmethod
    def _data(payload: Any) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise VerificationError("Unexpected 104 response structure")
        return payload["data"]

    @staticmethod
    def supported_custom_themes() -> dict:
        """Discover source-mapped theme capacities without site access."""
        return custom_theme_capabilities()

    @staticmethod
    def supported_patch_paths() -> dict:
        """Discover known JSON Patch targets without login or resume access."""
        return patch_path_catalog()

    async def list_resumes(self) -> list[dict]:
        data = self._data(await self.transport.get_json("/profile/ajax/overview"))
        overview = data.get("formData", {}).get("overview")
        if not isinstance(overview, list):
            raise VerificationError("104 resume list response changed")
        return overview

    async def get_resume(self, resume_id: str | int) -> dict:
        vno = self._version(resume_id)
        data = self._data(await self.transport.get_json(
            "/profile/ajax/resumeByBlock", params={"vno": vno}
        ))
        resume = data.get("resume")
        if not isinstance(resume, dict) or str(resume.get("vno")) != vno:
            raise ResumeNotFound("Requested resume version was not returned")
        return data

    async def get_section(self, resume_id: str | int, section: str) -> dict:
        """Read one named 104 section without stripping any native fields."""
        if section not in self.SECTIONS:
            raise ValueError("Unknown 104 editable section")
        document = await self.get_resume(resume_id)
        item = document.get(section)
        if not isinstance(item, (dict, list)):
            raise ResumeNotFound("Selected resume section is unavailable")
        return item

    async def get_editor_limits(self, section: str) -> dict:
        """Read the official editor's non-personal numeric field constraints."""
        if section not in INPUT_FIELD_GROUPS:
            raise UnsupportedWrite("104 editor limit section unsupported")
        response = self._data(await self.transport.get_json(
            "/profile/ajax/inputField"
        ))
        return native_editor_limits(response, section)

    async def get_language_editor_options(
        self, resume_id: str | int, kind: str,
    ) -> dict:
        """Read official per-kind LANGUAGE selectors and remaining capacity.

        This method makes no remote writes. An available unused type is not
        proof that a FOREIGN POST will succeed: unique foreign CREATE is
        still unverified on the live 104 resume editor.
        """
        if kind not in LANGUAGE_KINDS:
            raise UnsupportedWrite("104 LANGUAGE editor kind unsupported")
        version = self._version(resume_id)
        document = await self.get_resume(version)
        timestamp = document.get("resumeTimestamp")
        if not is_revision(timestamp):
            raise UnsupportedWrite("104 LANGUAGE current resume revision unavailable")
        records = language_lists(document)[kind]
        options = self._data(await self.transport.get_json("/profile/ajax/options"))
        fields = self._data(await self.transport.get_json("/profile/ajax/inputField"))
        choices = language_editor_choices(options, kind)
        maximum = language_capacity_limit(fields, kind)
        occupied = {int(row["type"]["value"]) for row in records}
        return {
            "resume_id": version,
            "resumeTimestamp": timestamp,
            "kind": kind,
            "count": len(records),
            "maximum": maximum,
            "remaining_capacity": max(0, maximum - len(records)),
            "occupied_type_ids": sorted(occupied),
            "selector_options": choices,
            "unused_type_options": [option for option in choices["type"]
                                    if option["value"] not in occupied],
            "source": "104-native-current-options",
            "persisted": False,
        }

    async def get_schema(self, resume_id: str | int) -> dict:
        document = await self.get_resume(resume_id)
        return {name: describe_schema(document[name])
                for name in self.SECTIONS if name in document}

    async def list_custom_slots(self, resume_id: str | int) -> list[dict]:
        """Read discovered numbered CUSTOM blocks without inferring their
        editable fields. The full GET can omit custom slots entirely.
        """
        document = await self.get_resume(resume_id)
        found = []
        for slot in self.CUSTOM_SLOTS:
            item = document.get(slot)
            if item is None:
                continue
            if not isinstance(item, dict):
                raise VerificationError(
                    "104 native CUSTOM block has an unexpected type"
                )
            found.append({
                "section": slot, "schema": describe_schema(item),
            })
        return found

    @staticmethod
    def _edit_timestamp(document: dict) -> str | int:
        """Require a real revision on every versioned PATCH plan.

        A GET without `resumeTimestamp` must never become a writable plan
        with base_timestamp=None. A subsequently missing or invalid version
        is also a conflict, rather than an implicit accept of None == None.
        """
        stamp = document.get("resumeTimestamp")
        if not is_revision(stamp):
            raise VerificationError("104 resume revision unavailable for an edit")
        return stamp

    async def plan_batch(
        self, resume_id: str | int, steps: list[dict], *,
        expected_timestamp: int | str,
    ) -> dict:
        """Read-only source/body preflight of the *first* batch operation."""
        return await preview_native_batch(
            self, resume_id, steps, expected_timestamp=expected_timestamp,
        )

    async def apply_batch(
        self, resume_id: str | int, steps: list[dict], *,
        expected_timestamp: int | str,
    ) -> dict:
        """Non-atomic workflow of existing record/PATCH/theme/sort writers."""
        return await apply_native_batch(
            self, resume_id, steps, expected_timestamp=expected_timestamp,
        )

    async def plan_edit(
        self, resume_id: str | int, changes: list[dict]
    ) -> tuple[EditPlan, dict]:
        document = await self.get_resume(resume_id)
        timestamp = self._edit_timestamp(document)
        operations = [JsonPatchOperation.from_dict(item) for item in changes]
        affected = {op.path.split("/")[1] if op.path.startswith("/") else ""
                    for op in operations}
        if not affected <= set(self.SECTIONS):
            raise ValueError("JSON Patch may affect only editable resume sections")
        # A PLAN is a prediction of which 104 writes are supported, not
        # merely a generic JSON document preview. Reject unsupported PATCH
        # operations and malformed native source shapes *before* returning
        # a plan that a caller could mistakenly consider safe to persist.
        paths = checked_write_paths(operations)
        sections = changed_sections(paths)
        updated = apply_json_patch(document, operations)
        for section in sections:
            validate_section_edit(document, updated, section)
            section_data(updated, section)
            section_request_body(updated, section)
        plan = EditPlan(
            resume_id=self._version(resume_id),
            base_timestamp=timestamp,
            operations=operations,
        )
        return plan, updated

    async def save_edit(self, plan: EditPlan) -> dict:
        """Persist only supported sections; verify each write independently.

        One section maps to one upstream PUT. Multiple sections are *not*
        atomic, and errors after a verified earlier write are surfaced as a
        PartialWriteError with no personal values. No upstream PUT is retried.
        """
        paths = checked_write_paths(plan.operations)
        sections = changed_sections(paths)
        verified_sections = []
        async with self._write_lock:
            current = await self.get_resume(plan.resume_id)
            stamp = self._edit_timestamp(current)
            require_revision_match(current, plan.base_timestamp)
            updated = apply_json_patch(current, plan.operations)
            # Validate every serializer before submitting even the first PUT.
            desired = {name: section_data(updated, name) for name in sections}
            before = {name: section_data(current, name) for name in sections}
            for name in sections:
                validate_section_edit(current, updated, name)
            bodies = {name: section_request_body(updated, name) for name in sections}
            latest = current
            for name in sections:
                if before[name] == desired[name]:
                    continue
                try:
                    # Every subsequent PUT gets a *new* source-of-truth GET.
                    # An external editor may have changed the pending block
                    # between our previous successful read-back and this PUT.
                    # Signed FILE access tokens are the only documented
                    # volatile exception; all other native blocks are stable.
                    if verified_sections:
                        refreshed = await self.get_resume(plan.resume_id)
                        # Metadata-only external edits can advance the
                        # global revision without changing a known block.
                        if not revision_matches(
                            refreshed, self._edit_timestamp(latest),
                        ) or not all(stable_block_equal(
                            latest, refreshed, block,
                        ) for block in PRESERVE_BLOCKS):
                            raise ConflictError(
                                "Resume changed between successive section writes"
                            )
                        latest = refreshed
                    # A cross-block PATCH is not atomic. The serializer body
                    # was built before the first PUT, so never overwrite a
                    # pending block if it changed while prior PUTs completed.
                    if not stable_block_equal(current, latest, name):
                        raise ConflictError(
                            "A pending resume section changed during the save"
                        )
                    # Do not automatically retry if the response is ambiguous.
                    pre_put = latest
                    await self.transport.put_json(
                        f"/profile/ajax/resumeByBlock/{name}",
                        bodies[name], params={"vno": plan.resume_id}
                    )
                    for attempt in range(4):
                        after = await self.get_resume(plan.resume_id)
                        latest = after
                        if verify_patch_transition(
                            pre_put, after, name, desired[name],
                        ):
                            verified_sections.append(name)
                            break
                        if attempt < 3:
                            await asyncio.sleep(0.75)
                    else:
                        raise VerificationError(
                            "104 section write was submitted but read-back "
                            "was not identical. Inspect before retrying."
                        )
                except Exception:
                    if verified_sections:
                        raise PartialWriteError(verified_sections, name) from None
                    raise
            return {
                "resume_id": plan.resume_id,
                "persisted": bool(verified_sections),
                "verified": True,
                "verified_sections": verified_sections,
                "changed_paths": [path for path in paths
                                  if path.split("/")[1] in verified_sections],
                "atomic": False,
            }

    async def mutate_skill(
        self,
        resume_id: str | int,
        action: str,
        *,
        expected_timestamp: int | str,
        changes: dict | None = None,
        position: int | None = None,
    ) -> dict:
        """Execute one source-mapped 104 SKILL record operation.

        The provider stores records individually and routes CREATE/UPDATE/
        DELETE to different HTTP methods. Never emulate these with a full
        skills-list replacement, and never retry ambiguous writes.
        """
        if action not in ("create", "update", "delete"):
            raise UnsupportedWrite("Unsupported 104 SKILL action")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before the skill operation")
            body = skill_operation_body(
                before, action, changes=changes, position=position
            )
            # Ensure all source-specific validation succeeds before any write.
            skill_list(before)
            method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
            await self.transport.request(
                method,
                "/profile/ajax/resumeByBlock/skill",
                params={"vno": version},
                json_data=body,
            )
            # An HTTP success does not prove that a record was committed.
            # Do not retry the mutation, even when the read-back is ambiguous.
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_skill_operation(
                        before, after, action, body=body, position=position
                    ) and verify_untouched_blocks(before, after, changed="skill"):
                        return {
                            "resume_id": version,
                            "action": action,
                            "section": "skill",
                            "persisted": True,
                            "verified": True,
                            "atomic": True,
                            "position": (
                                len(skill_list(after)) if action == "create"
                                else position
                            ),
                        }
                except Exception:
                    # Do not propagate unpredictable raw upstream data.
                    raise VerificationError(
                        "SKILL request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "SKILL request submitted but no exact matching record change "
                "could be verified; inspect before retrying"
            )

    async def mutate_education(
        self,
        resume_id: str | int,
        action: str,
        *,
        expected_timestamp: int | str,
        changes: dict | None = None,
        position: int | None = None,
    ) -> dict:
        """Source-mapped 104 EDUCATION record POST/PUT/DELETE.

        Each position is the current 1-based sort value. Unrecognized source
        shapes and stale resume versions are rejected before writing.
        """
        if action not in ("create", "update", "delete"):
            raise UnsupportedWrite("Unsupported 104 EDUCATION action")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before education operation")
            body = education_operation_body(
                before, action, changes=changes, position=position
            )
            education_list(before)
            method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
            await self.transport.request(
                method,
                "/profile/ajax/resumeByBlock/education",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_education_operation(
                        before, after, action, body=body, position=position
                    ) and verify_untouched_blocks(before, after, changed="education"):
                        return {
                            "resume_id": version,
                            "action": action,
                            "section": "education",
                            "persisted": True,
                            "verified": True,
                            "atomic": True,
                            "position": (
                                len(education_list(after)) if action == "create"
                                else position
                            ),
                        }
                except Exception:
                    raise VerificationError(
                        "EDUCATION request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "EDUCATION write submitted but record state could not be "
                "verified; inspect before retrying"
            )

    async def mutate_experience(
        self,
        resume_id: str | int,
        action: str,
        *,
        expected_timestamp: int | str,
        changes: dict | None = None,
        position: int | None = None,
    ) -> dict:
        """Source-mapped 104 EXPERIENCE record POST/PUT/DELETE.

        Each position is the current 1-based sort value. Unrecognized source
        shapes and stale resume versions are rejected before writing.
        """
        if action not in ("create", "update", "delete"):
            raise UnsupportedWrite("Unsupported 104 EXPERIENCE action")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before experience operation")
            body = experience_operation_body(
                before, action, changes=changes, position=position
            )
            experience_list(before)
            method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
            await self.transport.request(
                method,
                "/profile/ajax/resumeByBlock/experience",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_experience_operation(
                        before, after, action, body=body, position=position
                    ) and verify_untouched_blocks(before, after, changed="experience"):
                        return {
                            "resume_id": version,
                            "action": action,
                            "section": "experience",
                            "persisted": True,
                            "verified": True,
                            "atomic": True,
                            "position": (
                                len(experience_list(after)) if action == "create"
                                else position
                            ),
                        }
                except Exception:
                    raise VerificationError(
                        "EXPERIENCE request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "EXPERIENCE write submitted but record state could not be "
                "verified; inspect before retrying"
            )

    async def mutate_certificate_connections(
        self, resume_id: str | int, action: str, *,
        expected_timestamp: int | str,
        ids: list[int] | None = None,
        record_id: int | None = None,
    ) -> dict:
        """P0-07 browser-only official Vuex certificate import/disconnect.

        Uses official frontend action, not an inferred HTTP path. Requires
        initialized grouped GET, matching editor vno and browser action.
        Not yet live-verified on 104; never touches account-level cert CRUD.
        """
        if not isinstance(self.transport, BrowserTransport):
            raise UnsupportedWrite(
                "104 certificate associations require the official browser editor"
            )
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            require_revision_match(before, expected_timestamp)
            desired = validate_certificate_action(
                before, action=action, ids=ids, record_id=record_id,
            )
            await dispatch_certification_action(
                self.transport.page, resume_id=version, action=action,
                ids=ids or [], record_id=record_id,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    verified = verify_certificate_association(
                        before, after, desired_ids=desired,
                    ) and verify_untouched_blocks(
                        before, after, changed="certificate",
                    )
                except Exception:
                    raise VerificationError(
                        "104 certification action submitted; read-back unavailable"
                    ) from None
                if verified:
                    return {
                        "resume_id": version, "section": "certificate",
                        "action": action, "persisted": True, "verified": True,
                        "atomic": True, "linked_count": len(desired),
                        "source": "official_browser_vuex",
                    }
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 certification action submitted but exact state not verified"
            )

    async def mutate_certificate_block(
        self, resume_id: str | int, action: str, *,
        expected_timestamp: int | str, others: str | None = None,
    ) -> dict:
        """Create empty 104 CERTIFICATE block or clear its text-only content.

        Source-mapped from frontend module 779c; not live write-verified.
        Account-global certifications and linked certificate IDs are excluded.
        """
        if action not in ("initialize", "clear"):
            raise UnsupportedWrite("104 CERTIFICATE action unsupported")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before certificate operation")
            body = certificate_block_body(before, action, others=others)
            await self.transport.request(
                "PUT" if action == "initialize" else "DELETE",
                "/profile/ajax/resumeByBlock/certificate",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_certificate_block(
                        before, after, action, body=body
                    ) and verify_untouched_blocks(before, after, changed="certificate"):
                        return {
                            "resume_id": version, "section": "certificate",
                            "action": action, "persisted": True,
                            "verified": True, "atomic": True,
                        }
                except Exception:
                    raise VerificationError(
                        "104 CERTIFICATE submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 CERTIFICATE submitted but exact outcome not verified"
            )

    async def mutate_bio(
        self, resume_id: str | int, action: str, *,
        expected_timestamp: int | str, changes: dict | None = None,
    ) -> dict:
        """Explicit 104 BIO first POST or whole-section DELETE.

        Unlike the existing BIO PUT, these two operations have not yet
        been confirmed with a live write/read-back/restore.
        """
        if action not in ("create", "clear"):
            raise UnsupportedWrite("104 BIO operation must be create or clear")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before BIO operation")
            body = bio_action_body(before, action, changes=changes)
            await self.transport.request(
                "POST" if action == "create" else "DELETE",
                "/profile/ajax/resumeByBlock/bio",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_bio_action(before, after, action, body=body) and verify_untouched_blocks(
                        before, after, changed="bio",
                    ):
                        return {
                            "resume_id": version, "section": "bio",
                            "action": action, "persisted": True,
                            "verified": True, "atomic": True,
                        }
                except Exception:
                    raise VerificationError(
                        "104 BIO request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 BIO native write submitted; new state not verified"
            )

    async def mutate_under18(
        self,
        resume_id: str | int,
        action: str,
        *,
        changes: dict,
        expected_timestamp: int | str,
        acknowledge_identity_write: bool = False,
    ) -> dict:
        """Guarded 104 UNDER18 native POST/PUT (synthetic-tested only).

        Age or identity attestations must not be inferred from account state.
        Explicit consent is mandatory even when the caller uses the Python
        API directly, which has no HTTP/CLI opt-in flag to rely upon.
        Never echo birthdayDocument/idType or raw response on success.
        """
        if acknowledge_identity_write is not True:
            raise UnsupportedWrite("104 UNDER18 identity write needs explicit acknowledgement")
        if action not in ("create", "update"):
            raise UnsupportedWrite("104 UNDER18 supports create/update only")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume revision changed before UNDER18 write")
            body = under18_operation_body(before, action, changes=changes)
            await self.transport.request(
                "POST" if action == "create" else "PUT",
                "/profile/ajax/resumeByBlock/under18",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_under18_operation(
                        before, after, action, body=body,
                    ):
                        return {
                            "resume_id": version, "section": "under18",
                            "action": action, "persisted": True,
                            "verified": True, "atomic": True,
                            "contains_identity_values": False,
                            "live_sdk_verified": False,
                        }
                except Exception:
                    raise VerificationError(
                        "104 UNDER18 request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 UNDER18 request submitted; identity result unverified"
            )

    async def mutate_referrer(
        self,
        resume_id: str | int,
        action: str,
        *,
        expected_timestamp: int | str,
        changes: dict | None = None,
        position: int | None = None,
    ) -> dict:
        """Source-mapped 104 REFERRER record POST/PUT/DELETE.

        Each position is the current 1-based sort value. Unrecognized source
        shapes and stale resume versions are rejected before writing.
        """
        if action not in ("create", "update", "delete"):
            raise UnsupportedWrite("Unsupported 104 REFERRER action")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before referrer operation")
            form = before.get("referrer", {}).get("formData")
            if not isinstance(form, dict):
                raise UnsupportedWrite("104 REFERRER native formData missing")
            options = None
            if action == "create" and not form:
                options = self._data(
                    await self.transport.get_json("/profile/ajax/options")
                )
            body = referrer_operation_body(
                before, action, changes=changes, position=position,
                options=options,
            )
            referrer_records(before)
            method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
            await self.transport.request(
                method,
                "/profile/ajax/resumeByBlock/referrer",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_referrer_operation(
                        before, after, action, body=body, position=position
                    ) and verify_untouched_blocks(before, after, changed="referrer"):
                        return {
                            "resume_id": version,
                            "action": action,
                            "section": "referrer",
                            "persisted": True,
                            "verified": True,
                            "atomic": True,
                            "position": (
                                len(referrer_records(after)) if action == "create"
                                else position
                            ),
                        }
                except Exception:
                    raise VerificationError(
                        "REFERRER request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "REFERRER write submitted but record state could not be "
                "verified; inspect before retrying"
            )

    async def mutate_project(
        self,
        resume_id: str | int,
        action: str,
        *,
        expected_timestamp: int | str,
        changes: dict | None = None,
        position: int | None = None,
    ) -> dict:
        """Source-mapped 104 PROJECT record POST/PUT/DELETE.

        Each position is the current 1-based sort value. Unrecognized source
        shapes and stale resume versions are rejected before writing.
        """
        if action not in ("create", "update", "delete"):
            raise UnsupportedWrite("Unsupported 104 PROJECT action")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before project operation")
            form = before.get("project", {}).get("formData")
            if not isinstance(form, dict):
                raise UnsupportedWrite("104 PROJECT native formData missing")
            options = None
            if action == "create" and not form:
                options = self._data(
                    await self.transport.get_json("/profile/ajax/options")
                )
            body = project_operation_body(
                before, action, changes=changes, position=position,
                options=options,
            )
            project_records(before)
            method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
            await self.transport.request(
                method,
                "/profile/ajax/resumeByBlock/project",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_project_operation(
                        before, after, action, body=body, position=position
                    ) and verify_untouched_blocks(before, after, changed="project"):
                        return {
                            "resume_id": version,
                            "action": action,
                            "section": "project",
                            "persisted": True,
                            "verified": True,
                            "atomic": True,
                            "position": (
                                len(project_records(after)) if action == "create"
                                else position
                            ),
                        }
                except Exception:
                    raise VerificationError(
                        "PROJECT request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "PROJECT write submitted but record state could not be "
                "verified; inspect before retrying"
            )

    async def mutate_portfolio(
        self, resume_id: str | int, action: str, *,
        expected_timestamp: int | str,
        changes: dict | None = None,
        position: int | None = None,
    ) -> dict:
        """104 PORTFOLIO link-only POST or single-record DELETE.

        LINK creation uses multipart/form-data without a file payload;
        binary FILE upload is a separate operation, while media conversion
        and preview completion remain unverified.
        """
        if action not in ("create", "delete"):
            raise UnsupportedWrite("104 PORTFOLIO only supports link create/delete")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before portfolio operation")
            if action == "create":
                if position is not None:
                    raise UnsupportedWrite("104 PORTFOLIO create accepts no position")
                form = before.get("portfolio", {}).get("formData")
                if not isinstance(form, dict):
                    raise UnsupportedWrite("104 PORTFOLIO formData unavailable")
                options = None
                if not form:
                    options = self._data(
                        await self.transport.get_json("/profile/ajax/options")
                    )
                fields = portfolio_link_fields(before, changes, options=options)
                await self.transport.request(
                    "POST", "/profile/ajax/resumeByBlock/portfolio",
                    params={"vno": version}, multipart_fields=fields,
                )
            else:
                if changes is not None:
                    raise UnsupportedWrite("104 PORTFOLIO delete has no body")
                body = portfolio_delete_body(before, position=position)
                await self.transport.request(
                    "DELETE", "/profile/ajax/resumeByBlock/portfolio",
                    params={"vno": version}, json_data=body,
                )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    valid = (
                        verify_portfolio_link_create(
                            before, after, fields=fields
                        )
                        if action == "create"
                        else verify_portfolio_delete(
                            before, after, position=position
                        )
                    )
                    if valid and verify_untouched_blocks(
                        before, after, changed="portfolio",
                    ):
                        return {
                            "resume_id": version, "section": "portfolio",
                            "action": action,
                            "position": (
                                len(portfolio_records(after))
                                if action == "create" else position
                            ),
                            "persisted": True, "verified": True, "atomic": True,
                            "verification_scope": "display_identity",
                            "existing_attachment_bytes_verified": False,
                        }
                except Exception:
                    raise VerificationError(
                        "104 PORTFOLIO submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 PORTFOLIO submitted but exact result not verified"
            )

    async def upload_portfolio_file(
        self, resume_id: str | int, *,
        expected_timestamp: int | str,
        name: str, attach_name: str,
        filename: str, content_type: str, content: bytes,
    ) -> dict:
        """Source-mapped experimental PORTFOLIO file POST.

        Sends at most 5 MiB via authenticated multipart/form-data.
        The site may require additional asynchronous conversion/preview
        actions, which are not yet verified. Never retries an uncertain
        remote upload and never deletes existing attachments to recover.
        """
        version = self._version(resume_id)
        upload = BrowserUpload(
            field_name="attachment", filename=filename,
            content_type=content_type, content=content,
        )
        upload.validate()
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before portfolio file upload")
            form = before.get("portfolio", {}).get("formData")
            if not isinstance(form, dict):
                raise UnsupportedWrite("104 PORTFOLIO formData unavailable")
            options = None
            if not form:
                options = self._data(await self.transport.get_json(
                    "/profile/ajax/options"
                ))
            fields = portfolio_file_fields(
                before, {"name": name, "attachName": attach_name},
                options=options,
            )
            await self.transport.request(
                "POST", "/profile/ajax/resumeByBlock/portfolio",
                params={"vno": version},
                multipart_fields=fields, multipart_upload=upload,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_portfolio_file_create(
                        before, after, fields=fields,
                    ) and verify_untouched_blocks(before, after, changed="portfolio"):
                        return {
                            "resume_id": version, "section": "portfolio",
                            "action": "create-file", "persisted": True,
                            "verified": True, "atomic": True,
                            "preview_verified": False,
                            "verification_scope": "addressable_file_record",
                            "existing_attachment_bytes_verified": False,
                        }
                except Exception:
                    raise VerificationError(
                        "104 PORTFOLIO file submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 PORTFOLIO uploaded file; stable record not verified"
            )

    async def request_portfolio_conversion(
        self, resume_id: str | int, *, expected_timestamp: int | str,
        filename: str, content_type: str, content: bytes,
    ) -> dict:
        """Submit one file to official BFF conversion, without a retry.

        This endpoint is distinct from attaching a file to PORTFOLIO.
        A 2xx response means acceptance only, not completed previews,
        persistent resume edits, or backend blob removal.
        """
        version=self._version(resume_id)
        item=BrowserUpload(
            field_name="convertPreviewThumbnail",
            filename=filename,content_type=content_type,content=content,
        )
        item.validate()
        async with self._write_lock:
            before=await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before conversion request")
            response=await self.transport.request(
                "POST","/api/resumes/files/convert-preview-thumbnail",
                multipart_fields={},multipart_upload=item,
            )
            raw=self._data(response.data)
            # Do not expose signed/opaque service URLs or generated IDs
            # in CLI/HTTP by default; callers can separately inspect
            # their authenticated conversion/status workflow.
            return {
                "resume_id":version,"section":"portfolio",
                "action":"request-conversion",
                "submitted":True,"server_accepted":True,
                "preview_verified":False,
                "created_resume_attachment":False,
                "conversion_response_fields":sorted(raw),
                "temporary_backend_blob_cleanup_unverified":True,
            }

    async def get_portfolio_conversion_status(
        self, resume_id: str | int, *, position: int,
        tag: str = "undefined",
    ) -> dict:
        """Read the official 104 conversion status for a resume's FILE.

        The source frontend 44aa does not set tag for portfolio GET,
        producing tag=undefined. Never starts a conversion, downloads
        protected files, or exposes rotating access URLs.
        """
        if not isinstance(tag,str) or not tag or len(tag)>64 or not all(
            x.isalnum() or x in "_-" for x in tag
        ):
            raise UnsupportedWrite("Invalid 104 conversion-status tag")
        version=self._version(resume_id)
        before=await self.get_resume(version)
        file_id=conversion_file_id(before,position=position)
        raw=await self.transport.get_json(
            "/api/resumes/files/convert-status",
            params={"fileId":file_id,"tag":tag},
        )
        return {
            "resume_id":version,"section":"portfolio","position":position,
            **convert_status_summary(raw),
        }

    async def mutate_custom_text(
        self, resume_id: str | int, action: str, *, slot: int,
        expected_timestamp: int | str,
        name: str | None = None,
        introduction_html: str | None = None,
    ) -> dict:
        """104 TEXT=3 CUSTOM native POST/PUT/DELETE, verified by fresh GET.

        A real custom1 single-text record lifecycle was confirmed on
        2026-11-17 with a private empty-slot test and exact restore.
        Other custom theme/media variants remain unsupported.
        """
        if action not in ("create", "update", "delete"):
            raise UnsupportedWrite("104 CUSTOM TEXT unsupported action")
        # Every operation uses source-validated 1..6 dynamic slots.
        if type(slot) is not int or not 1 <= slot <= 6:
            raise UnsupportedWrite("104 CUSTOM slot must be custom1..custom6")
        version=self._version(resume_id)
        async with self._write_lock:
            before=await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 CUSTOM changed before operation")
            existing=custom_text_form(before,slot=slot)
            if action=="create":
                if existing is not None or name is None or introduction_html is None:
                    raise UnsupportedWrite(
                        "104 CUSTOM first-create requires an empty slot, name and HTML"
                    )
                opts=self._data(await self.transport.get_json("/profile/ajax/options"))
                body=custom_text_create_body(
                    slot=slot,name=name,introduction_html=introduction_html,
                    theme_options=opts,
                )
            elif action=="update":
                if existing is None:
                    raise UnsupportedWrite("104 CUSTOM update requires a native TEXT form")
                body=custom_text_update_body(
                    existing,name=name,introduction_html=introduction_html,
                )
            else:
                if existing is None or name is not None or introduction_html is not None:
                    raise UnsupportedWrite(
                        "104 CUSTOM delete requires an existing TEXT slot, no fields"
                    )
                body=custom_delete_body(slot=slot)
            method={"create":"POST","update":"PUT","delete":"DELETE"}[action]
            await self.transport.request(
                method,"/profile/ajax/resumeByBlock/custom",
                params={"vno":version},json_data=body,
            )
            for attempt in range(4):
                try:
                    after=await self.get_resume(version)
                    if verify_custom_text_mutation(
                        before,after,action,slot=slot,body=body
                    ) and verify_untouched_blocks(before, after, changed=f"custom{slot}"):
                        return {
                            "resume_id":version,"section":f"custom{slot}",
                            "action":action,"persisted":True,"verified":True,
                            "atomic":True,"theme":"TEXT",
                        }
                except Exception:
                    raise VerificationError(
                        "104 CUSTOM submitted, read-back unavailable; inspect first"
                    ) from None
                if attempt<3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 CUSTOM request submitted but target was not verified"
            )

    async def mutate_custom_layout(
        self, resume_id: str | int, action: str, *, slot: int,
        expected_timestamp: int | str,
        theme: int | None = None, name: str | None = None,
        content: dict | None = None,
    ) -> dict:
        """Guarded CLASSIC/BANNER single no-media CUSTOM slot CRUD.

        This wraps the earlier raw native site-tested request; the combined
        SDK/HTTP flows have synthetic tests only. Never retries a mutation
        with ambiguous results, and never overwrites another custom theme.
        """
        if action not in ("create", "update", "delete"):
            raise UnsupportedWrite("104 CUSTOM layout unsupported action")
        if type(slot) is not int or not 1 <= slot <= 6:
            raise UnsupportedWrite("104 CUSTOM layout invalid slot")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 CUSTOM layout revision changed before operation")
            options = None
            if action == "create":
                if f"custom{slot}" in before:
                    raise UnsupportedWrite("104 CUSTOM layout slot already occupied")
                options = self._data(await self.transport.get_json(
                    "/profile/ajax/options"
                ))
            body = layout_operation_body(
                before, action, slot=slot, theme=theme, name=name,
                content=content, options=options,
            )
            method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
            await self.transport.request(
                method, "/profile/ajax/resumeByBlock/custom",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    matched = verify_layout_mutation(
                        before, after, action, slot=slot, body=body,
                    )
                except Exception:
                    raise VerificationError(
                        "104 CUSTOM layout submitted; read-back unavailable"
                    ) from None
                if matched and verify_untouched_blocks(
                    before, after, changed=f"custom{slot}",
                ):
                    current_theme = (
                        theme if action == "create" else
                        before[f"custom{slot}"]["formData"]["themeChoose"]
                        ["selectedTheme"]["value"]
                    )
                    return {
                        "resume_id": version, "section": f"custom{slot}",
                        "action": action, "theme": LAYOUT_THEMES[current_theme],
                        "persisted": True, "verified": True, "atomic": True,
                    }
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 CUSTOM layout request submitted but exact result unverified"
            )

    async def mutate_language(
        self,
        resume_id: str | int,
        kind: str, action: str,
        *,
        expected_timestamp: int | str,
        changes: dict | None = None,
        position: int | None = None,
    ) -> dict:
        """Source-mapped 104 LANGUAGE record POST/PUT/DELETE.

        Each position is the current 1-based sort value. Unrecognized source
        shapes and stale resume versions are rejected before writing.
        """
        if kind not in LANGUAGE_KINDS or action not in ("create", "update", "delete"):
            raise UnsupportedWrite("Unsupported 104 LANGUAGE action")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before language operation")
            body = language_operation_body(
                before, kind, action, changes=changes, position=position
            )
            records = language_lists(before)
            if action == "create":
                fields = self._data(await self.transport.get_json(
                    "/profile/ajax/inputField"
                ))
                validate_language_capacity(fields, kind, len(records[kind]))
            if action != "delete":
                # Official editor selects from /options lists. Validate those
                # live and fail before POST/PUT instead of guessing language IDs
                # or silently accepting mismatched displayed language labels.
                options = self._data(await self.transport.get_json(
                    "/profile/ajax/options"
                ))
                validate_language_selectors(options, kind, changes)
            method = {"create": "POST", "update": "PUT", "delete": "DELETE"}[action]
            await self.transport.request(
                method,
                "/profile/ajax/resumeByBlock/language",
                params={"vno": version}, json_data=body,
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_language_operation(
                        before, after, kind, action, body=body, position=position
                    ) and verify_untouched_blocks(before, after, changed="language"):
                        return {
                            "resume_id": version,
                            "action": action,
                            "section": "language",
                            "kind": kind,
                            "persisted": True,
                            "verified": True,
                            "atomic": True,
                            "position": (
                                len(language_lists(after)[kind]) if action == "create"
                                else position
                            ),
                        }
                except Exception:
                    raise VerificationError(
                        "LANGUAGE request submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "LANGUAGE write submitted but record state could not be "
                "verified; inspect before retrying"
            )

    async def set_theme(
        self, resume_id: str | int, section: str, selected_theme: int, *,
        expected_timestamp: int | str,
    ) -> dict:
        """104 native LAYOUT operation, validated against current site options."""
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("104 resume changed before theme selection")
            options = self._data(await self.transport.get_json("/profile/ajax/options"))
            body = theme_body(before, options, section, selected_theme)
            if native_theme(before, section) == selected_theme:
                return {
                    "resume_id": version, "section": section,
                    "selected_theme": selected_theme, "persisted": False,
                    "verified": True, "atomic": True,
                }
            latest = await self.get_resume(version)
            if (
                not revision_matches(latest, expected_timestamp)
                or latest.get(section) != before.get(section)
            ):
                raise ConflictError("104 resume changed while validating theme")
            await self.transport.put_json(
                "/profile/ajax/resumeByBlock/layout", body,
                params={"vno": version},
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_theme_write(before, after, section, selected_theme) and verify_untouched_blocks(
                        before, after, changed=section,
                    ):
                        return {
                            "resume_id": version, "section": section,
                            "selected_theme": selected_theme,
                            "persisted": True, "verified": True, "atomic": True,
                        }
                except Exception:
                    raise VerificationError(
                        "104 LAYOUT submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 LAYOUT submitted; changed theme was not verified"
            )

    async def sort_records(
        self, resume_id: str | int, section: str, from_position: int,
        to_position: int, *, expected_timestamp: int | str,
        kind: str | None = None,
    ) -> dict:
        """Adjacent native 104 sort for supported sections.

        A two-item PORTFOLIO swap/reverse was verified on real 104;
        other section sorts remain source-mapped/synthetic-tested.
        """
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if not revision_matches(before, expected_timestamp):
                raise ConflictError("Resume changed before native sort operation")
            body = sort_body(
                before, section, from_position, to_position, kind=kind
            )
            await self.transport.put_json(
                f"/profile/ajax/swapRecordBySort/{section}", body,
                params={"vno": version},
            )
            for attempt in range(4):
                try:
                    after = await self.get_resume(version)
                    if verify_sort(
                        before, after, section, from_position, to_position,
                        kind=kind,
                    ) and verify_untouched_blocks(before, after, changed=section):
                        return {
                            "resume_id": version, "section": section,
                            "from": from_position, "to": to_position,
                            **({"kind": kind} if kind is not None else {}),
                            "persisted": True, "verified": True, "atomic": True,
                            **({"verification_scope": "display_identity",
                                "existing_attachment_bytes_verified": False}
                               if section == "portfolio" else {}),
                        }
                except Exception:
                    raise VerificationError(
                        "104 sort submitted; read-back unavailable"
                    ) from None
                if attempt < 3:
                    await asyncio.sleep(0.75)
            raise VerificationError(
                "104 sort submitted but exact move not verified"
            )

    async def create_resume(self) -> dict:
        """Create one actual resume; do not blindly retry ambiguous failures."""
        if self.page is None:
            raise UnsupportedWrite(
                "104 resume creation requires browser UI; use browser transport"
            )
        old_list = await self.list_resumes()
        before = {str(item.get("versionNo")) for item in old_list}
        await self.page.goto(
            "https://pda.104.com.tw/profile",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await self.page.wait_for_timeout(2500)
        if not await self.transport.ensure_authenticated():
            raise AuthenticationRequired("104 resume session unavailable")
        add = self.page.get_by_role("button", name="新增履歷", exact=True)
        if await add.count() != 1:
            raise VerificationError("Unique Add Resume control was not found")
        await add.click(timeout=15000)
        await self.page.wait_for_timeout(1100)
        start = self.page.get_by_role("button", name="開始製作", exact=True)
        if await start.count() != 1:
            raise VerificationError("Unique Start Making control was not found")
        async with self.page.expect_response(
            lambda res: res.request.method == "POST"
            and url_without_query(res.url)
            == "https://pda.104.com.tw/profile/ajax/createResume",
            timeout=30000,
        ) as future:
            await start.click(timeout=15000, no_wait_after=True)
        response = await future.value
        if response.status != 200:
            raise VerificationError("104 did not confirm resume creation")
        await self.page.wait_for_timeout(2500)
        after = await self.list_resumes()
        new = [x for x in after if str(x.get("versionNo")) not in before]
        if len(new) != 1:
            raise VerificationError(
                "Create may have succeeded but list delta is inconclusive; "
                "inspect the list before another create attempt"
            )
        return new[0]


def url_without_query(url: str) -> str:
    return url.split("?", 1)[0]
