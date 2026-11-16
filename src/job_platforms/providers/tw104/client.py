"""104 resume read, create and local multi-field editing.

Persisted edits to existing resumes deliberately remain unsupported until
each upstream section writer has been verified against website read-back.
"""
from __future__ import annotations

import re
from typing import Any

from job_platforms.core.errors import (
    AuthenticationRequired, ConflictError, ResumeNotFound, UnsupportedWrite,
    VerificationError,
)
from job_platforms.core.patch import (
    EditPlan, JsonPatchOperation, apply_json_patch, describe_schema,
)
from .transport import BrowserTransport


class Resume104Client:
    SECTIONS = (
        "info", "education", "experience", "jobCondition", "skill",
        "certificate", "language", "project", "portfolio", "bio",
        "referrer",
    )

    def __init__(self, page: Any):
        self.page = page
        self.transport = BrowserTransport(page)

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
        current = await self.get_resume(plan.resume_id)
        if current.get("resumeTimestamp") != plan.base_timestamp:
            raise ConflictError("Resume changed since the edit plan was prepared")
        raise UnsupportedWrite(
            "104 save adapters have not yet been verified; no edit was submitted"
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
