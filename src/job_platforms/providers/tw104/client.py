"""104 resume read, create and local multi-field editing.

Persisted edits to existing resumes deliberately remain unsupported until
each upstream section writer has been verified against website read-back.
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
from .transport import BrowserTransport
from .skill_records import skill_list, skill_operation_body, verify_skill_operation
from .record_sort import SORTABLE, sort_body, verify_sort
from .layout_theme import (
    THEME_OPTION_KEYS, native_theme, theme_body, verify_theme_write,
)
from .language_records import (
    KINDS as LANGUAGE_KINDS, language_lists, language_operation_body,
    verify_language_operation,
)
from .bio_actions import bio_action_body, verify_bio_action
from .project_records import (
    project_records, project_operation_body, verify_project_operation,
)
from .portfolio_records import (
    portfolio_records, portfolio_delete_body, verify_portfolio_delete,
    portfolio_link_fields, verify_portfolio_link_create,
)
from .referrer_records import (
    referrer_records, referrer_operation_body, verify_referrer_operation,
)
from .experience_records import (
    experience_list, experience_operation_body, verify_experience_operation,
)
from .education_records import (
    education_list, education_operation_body, verify_education_operation,
)
from .writers import (
    checked_write_paths, changed_sections, section_data, section_request_body,
    validate_section_edit,
)


class Resume104Client:
    SECTIONS = (
        "info", "education", "experience", "jobCondition", "skill",
        "certificate", "language", "project", "portfolio", "bio",
        "referrer", "sidebar",
    )

    def __init__(self, page: Any):
        self.page = page
        self.transport = BrowserTransport(page)
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

    async def get_schema(self, resume_id: str | int) -> dict:
        document = await self.get_resume(resume_id)
        return {name: describe_schema(document[name])
                for name in self.SECTIONS if name in document}

    async def plan_edit(
        self, resume_id: str | int, changes: list[dict]
    ) -> tuple[EditPlan, dict]:
        document = await self.get_resume(resume_id)
        operations = [JsonPatchOperation.from_dict(item) for item in changes]
        affected = {op.path.split("/")[1] if op.path.startswith("/") else ""
                    for op in operations}
        if not affected <= set(self.SECTIONS):
            raise ValueError("JSON Patch may affect only editable resume sections")
        updated = apply_json_patch(document, operations)
        plan = EditPlan(
            resume_id=self._version(resume_id),
            base_timestamp=document.get("resumeTimestamp"),
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
            if current.get("resumeTimestamp") != plan.base_timestamp:
                raise ConflictError("Resume changed since the edit plan was prepared")
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
                    # Prior section read-backs refresh the version header. Never
                    # use that fresh header to overwrite a stale pending block.
                    # A cross-block transaction is not atomic; this detects
                    # intervening changes before each subsequent request.
                    if section_data(latest, name) != before[name]:
                        raise ConflictError(
                            "A pending resume section changed during the save"
                        )
                    # Do not automatically retry if the response is ambiguous.
                    await self.transport.put_json(
                        f"/profile/ajax/resumeByBlock/{name}",
                        bodies[name], params={"vno": plan.resume_id}
                    )
                    for attempt in range(4):
                        after = await self.get_resume(plan.resume_id)
                        latest = after
                        if section_data(after, name) == desired[name]:
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    ):
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    ):
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    ):
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    if verify_bio_action(before, after, action, body=body):
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    ):
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    ):
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

        Link creation uses browser FormData with no file payload. Other
        attachments require unimplemented upload/conversion workflows.
        """
        if action not in ("create", "delete"):
            raise UnsupportedWrite("104 PORTFOLIO only supports link create/delete")
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    if valid:
                        return {
                            "resume_id": version, "section": "portfolio",
                            "action": action,
                            "position": (
                                len(portfolio_records(after))
                                if action == "create" else position
                            ),
                            "persisted": True, "verified": True, "atomic": True,
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
                raise ConflictError("104 resume changed before language operation")
            body = language_operation_body(
                before, kind, action, changes=changes, position=position
            )
            language_lists(before)
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
                    ):
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
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                str(latest.get("resumeTimestamp")) != str(expected_timestamp)
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
                    if verify_theme_write(before, after, section, selected_theme):
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
        """Adjacent 104 SKILL/EDUCATION or local/foreign LANGUAGE sort."""
        version = self._version(resume_id)
        async with self._write_lock:
            before = await self.get_resume(version)
            if str(before.get("resumeTimestamp")) != str(expected_timestamp):
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
                    ):
                        return {
                            "resume_id": version, "section": section,
                            "from": from_position, "to": to_position,
                            **({"kind": kind} if kind is not None else {}),
                            "persisted": True, "verified": True, "atomic": True,
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
