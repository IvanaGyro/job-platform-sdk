"""Optional local FastAPI service using the same browser-backed 104 client.

Authentication is required for all routes other than /healthz.
No HTTP port is exposed publicly by default. The service runs one shared
browser session for its lifetime and serializes non-idempotent operations.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request

from job_platforms.core.capabilities import ProviderCapabilities
from job_platforms.core.errors import (
    AuthenticationRequired, ConflictError, JobPlatformError, ResumeNotFound,
    UnsupportedWrite, UpstreamError, VerificationError, PartialWriteError,
)
from job_platforms.providers.tw104 import AuthConfig, FreshBrowserSession, Resume104Client
from job_platforms.providers.tw104.skill_records import skill_operation_body
from job_platforms.providers.tw104.education_records import education_operation_body
from job_platforms.providers.tw104.experience_records import experience_operation_body
from job_platforms.providers.tw104.referrer_records import referrer_operation_body
from job_platforms.providers.tw104.project_records import project_operation_body
from job_platforms.providers.tw104.portfolio_records import (
    portfolio_delete_body, portfolio_link_fields,
    portfolio_file_fields,
)
from job_platforms.providers.tw104.bio_actions import bio_action_body
from job_platforms.providers.tw104.transport import (
    BrowserUpload, MAX_BROWSER_UPLOAD_BYTES,
)
from job_platforms.providers.tw104.certificate_block_actions import (
    certificate_block_body,
)
from job_platforms.providers.tw104.custom_text_contract import (
    custom_text_form, custom_text_create_body, custom_text_update_body,
    custom_delete_body,
)
from job_platforms.providers.tw104.language_records import (
    language_operation_body, language_lists,
    validate_language_selectors, validate_language_capacity,
    KINDS as LANGUAGE_KINDS,
)
from job_platforms.providers.tw104.layout_theme import THEME_OPTION_KEYS, theme_body
from job_platforms.providers.tw104.record_sort import SORTABLE, sort_body


TW104_CAPABILITIES = ProviderCapabilities(
    provider="tw104", list_resumes=True, get_resume=True,
    create_resume=True, plan_edit=True, save_edit=False,
)


def create_app(
    config: AuthConfig | None = None, *, api_token: str | None = None,
    allow_experimental_writes: bool | None = None,
) -> FastAPI:
    token = api_token or os.getenv("JOB_PLATFORM_API_TOKEN")
    if not token or len(token) < 24:
        raise ValueError("JOB_PLATFORM_API_TOKEN must contain at least 24 characters")
    config = config or AuthConfig.from_env()
    if allow_experimental_writes is None:
        allow_experimental_writes = (
            os.getenv("JOB_PLATFORM_104_ENABLE_EXPERIMENTAL_WRITES") == "1"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with FreshBrowserSession(config) as session:
            transport = os.getenv("JOB_PLATFORM_104_TRANSPORT", "browser")
            if transport == "browser":
                app.state.client = Resume104Client(session.page)
            else:
                app.state.client = await session.resume_client(
                    transport=transport,
                    allow_http_writes=(
                        allow_experimental_writes
                        and os.getenv("JOB_PLATFORM_104_CFFI_ENABLE_WRITES") == "1"
                    ),
                )
            app.state.action_lock = asyncio.Lock()
            app.state.idempotency_results = {}
            yield

    app = FastAPI(
        title="Job Platform SDK (unofficial)",
        version="0.1.0a1",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    async def authorize(authorization: str | None = Header(default=None)):
        expected = "Bearer " + token
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Authentication required")

    def require_provider(provider: str):
        if provider != "tw104":
            raise HTTPException(status_code=501, detail="Provider not implemented")

    def translate_error(exc: JobPlatformError):
        if isinstance(exc, AuthenticationRequired):
            raise HTTPException(503, "104 browser session unavailable") from None
        if isinstance(exc, ResumeNotFound):
            raise HTTPException(404, "Resume not found") from None
        if isinstance(exc, ConflictError):
            raise HTTPException(409, "Resume changed since last read") from None
        if isinstance(exc, UnsupportedWrite):
            raise HTTPException(501, "Save operation not implemented") from None
        if isinstance(exc, PartialWriteError):
            raise HTTPException(
                409, {
                    "reason": "Partial multi-section write; do not retry blindly",
                    "verified_sections": exc.verified_sections,
                    "failed_section": exc.failed_section,
                },
            ) from None
        if isinstance(exc, VerificationError):
            raise HTTPException(
                409, "Website result not verified; inspect before retrying"
            ) from None
        if isinstance(exc, UpstreamError):
            raise HTTPException(502, f"Upstream HTTP {exc.status}") from None
        raise HTTPException(500, "Provider request failed") from None

    @app.get("/healthz")
    async def healthz():
        return {"service": "job-platform", "status": "ready"}

    @app.get("/v1/providers", dependencies=[Depends(authorize)])
    async def providers():
        return {
            "tw104": {
                **TW104_CAPABILITIES.to_dict(),
                "experimental_writable_sections": [
                    "bio", "certificate", "sidebar", "jobCondition",
                    "experience.seniority", "info.resumeFields",
                ],
                "experimental_theme_sections": list(THEME_OPTION_KEYS),
                "experimental_sort_sections": list(SORTABLE),
                "experimental_custom_text_actions": ["create","update","delete"],
                "experimental_bio_actions": ["create", "clear"],
                "experimental_record_operations": {
                    "skill": ["create", "update", "delete"],
                    "education": ["create", "update", "delete"],
                    "experience": ["create", "update", "delete"],
                    "referrer": ["create", "update", "delete"],
                    "project": ["create", "update", "delete"],
                    "portfolio": ["create-link", "create-file", "delete"],
                    "language.local": ["create", "update", "delete"],
                    "language.foreign": ["create", "update", "delete"],
                },
                "experimental_writes_enabled": allow_experimental_writes,
            },
            "cake": {"provider": "cake", "implemented": False},
            "yourator": {"provider": "yourator", "implemented": False},
            "greenhouse": {"provider": "greenhouse", "implemented": False},
        }

    @app.get("/v1/{provider}/resumes", dependencies=[Depends(authorize)])
    async def list_resumes(provider: str, request: Request):
        require_provider(provider)
        try:
            async with request.app.state.action_lock:
                return await request.app.state.client.list_resumes()
        except JobPlatformError as exc:
            translate_error(exc)

    @app.get("/v1/{provider}/resumes/{resume_id}", dependencies=[Depends(authorize)])
    async def get_resume(provider: str, resume_id: str, request: Request):
        require_provider(provider)
        try:
            async with request.app.state.action_lock:
                return await request.app.state.client.get_resume(resume_id)
        except JobPlatformError as exc:
            translate_error(exc)

    @app.get(
        "/v1/{provider}/resumes/{resume_id}/schema",
        dependencies=[Depends(authorize)],
    )
    async def resume_schema(provider: str, resume_id: str, request: Request):
        require_provider(provider)
        try:
            async with request.app.state.action_lock:
                return await request.app.state.client.get_schema(resume_id)
        except JobPlatformError as exc:
            translate_error(exc)

    async def custom_text_http(
        resume_id: str,request: Request,action: str,slot: int,
        changes: dict | None,if_match: str | None,
        idempotency_key: str | None,
    ):
        if not allow_experimental_writes:
            raise HTTPException(501,"104 CUSTOM requires experimental opt-in")
        if if_match is None:
            raise HTTPException(428,"If-Match resumeTimestamp required")
        if not idempotency_key or len(idempotency_key)<16:
            raise HTTPException(400,"Idempotency-Key needs at least 16 characters")
        if type(slot) is not int or not 1<=slot<=6:
            raise HTTPException(422,"CUSTOM slot must be 1 through 6")
        if not isinstance(changes,dict) or set(changes)-{
            "name","introduction_html"
        }:
            raise HTTPException(422,"Unknown CUSTOM text field")
        name=changes.get("name")
        html=changes.get("introduction_html")
        if action=="create" and (
            set(changes)!={"name","introduction_html"}
        ):
            raise HTTPException(422,"CUSTOM create needs name and introduction_html")
        if action=="update" and not changes:
            raise HTTPException(422,"CUSTOM update needs changed fields")
        if action=="delete" and changes:
            raise HTTPException(422,"CUSTOM delete takes no fields")
        expected=if_match.strip('"')
        fingerprint=hashlib.sha256(json.dumps({
            "action":action,"slot":slot,"changes":changes,
            "timestamp":expected,
        },sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
        key=("CUSTOM_TEXT",resume_id,idempotency_key)
        async with request.app.state.action_lock:
            record=request.app.state.idempotency_results.get(key)
            if record is not None:
                if record["fingerprint"]!=fingerprint:
                    raise HTTPException(409,"Idempotency-Key reused for different operation")
                if record["state"]!="succeeded":
                    raise HTTPException(409,"CUSTOM write outcome uncertain; inspect first")
                return record["result"]
            try:
                before=await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp"))!=expected:
                    raise HTTPException(412,"Resume changed since prior GET")
                existing=custom_text_form(before,slot=slot)
                if action=="create":
                    if existing is not None:
                        raise UnsupportedWrite("CUSTOM slot already exists")
                    opts=request.app.state.client._data(
                        await request.app.state.client.transport.get_json(
                            "/profile/ajax/options"
                        )
                    )
                    custom_text_create_body(
                        slot=slot,name=name,introduction_html=html,
                        theme_options=opts,
                    )
                elif action=="update":
                    if existing is None:
                        raise UnsupportedWrite("CUSTOM slot absent")
                    custom_text_update_body(
                        existing,name=name,introduction_html=html,
                    )
                else:
                    if existing is None:
                        raise UnsupportedWrite("CUSTOM slot absent")
                    custom_delete_body(slot=slot)
            except (UnsupportedWrite,ValueError,KeyError,TypeError):
                raise HTTPException(422,"Invalid or unsupported CUSTOM TEXT fields") from None
            except JobPlatformError as exc:
                translate_error(exc)
            entry={"fingerprint":fingerprint,"state":"indeterminate"}
            request.app.state.idempotency_results[key]=entry
            try:
                result=await request.app.state.client.mutate_custom_text(
                    resume_id,action,slot=slot,expected_timestamp=expected,
                    name=name,introduction_html=html,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                entry.update({"state":"succeeded","result":result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/custom-text",
        dependencies=[Depends(authorize)],
    )
    async def create_custom_text(
        resume_id: str,request: Request,changes: dict = Body(...),
        if_match: str | None = Header(default=None,alias="If-Match"),
        idempotency_key: str | None = Header(default=None,alias="Idempotency-Key"),
    ):
        slot=changes.get("slot")
        if type(slot) is not int:
            raise HTTPException(422,"CUSTOM slot is required")
        payload={k:v for k,v in changes.items() if k!="slot"}
        return await custom_text_http(
            resume_id,request,"create",slot,payload,
            if_match,idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/custom-text/{slot}",
        dependencies=[Depends(authorize)],
    )
    async def update_custom_text(
        resume_id: str,slot: int,request: Request,changes: dict=Body(...),
        if_match: str | None = Header(default=None,alias="If-Match"),
        idempotency_key: str | None = Header(default=None,alias="Idempotency-Key"),
    ):
        return await custom_text_http(
            resume_id,request,"update",slot,changes,
            if_match,idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/custom-text/{slot}",
        dependencies=[Depends(authorize)],
    )
    async def delete_custom_text(
        resume_id: str,slot: int,request: Request,
        if_match: str | None = Header(default=None,alias="If-Match"),
        idempotency_key: str | None = Header(default=None,alias="Idempotency-Key"),
    ):
        return await custom_text_http(
            resume_id,request,"delete",slot,{},
            if_match,idempotency_key,
        )

    @app.get(
        "/v1/tw104/resumes/{resume_id}/custom-slots",
        dependencies=[Depends(authorize)],
    )
    async def list_native_custom_slots(resume_id: str, request: Request):
        try:
            async with request.app.state.action_lock:
                return await request.app.state.client.list_custom_slots(resume_id)
        except JobPlatformError as exc:
            translate_error(exc)

    @app.get(
        "/v1/{provider}/resumes/{resume_id}/sections/{section}",
        dependencies=[Depends(authorize)],
    )
    async def resume_section(provider: str, resume_id: str, section: str, request: Request):
        require_provider(provider)
        if section not in Resume104Client.SECTIONS:
            raise HTTPException(400, "Unknown resume section")
        try:
            async with request.app.state.action_lock:
                return await request.app.state.client.get_section(resume_id, section)
        except JobPlatformError as exc:
            translate_error(exc)

    @app.post("/v1/{provider}/resumes", dependencies=[Depends(authorize)])
    async def create_resume(
        provider: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        require_provider(provider)
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters is required")
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(
                (provider, idempotency_key)
            )
            if cached is not None:
                if cached["state"] == "succeeded":
                    return cached["result"]
                raise HTTPException(
                    409, "Create outcome is indeterminate; inspect resumes before retrying"
                )
            cache_key = (provider, idempotency_key)
            request.app.state.idempotency_results[cache_key] = {
                "state": "indeterminate"
            }
            try:
                item = await request.app.state.client.create_resume()
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                request.app.state.idempotency_results[cache_key] = {
                    "state": "succeeded", "result": item
                }
                return item

    @app.post(
        "/v1/{provider}/resumes/{resume_id}/plan",
        dependencies=[Depends(authorize)],
    )
    async def edit_plan(
        provider: str, resume_id: str, request: Request,
        operations: list[dict] = Body(...),
    ):
        require_provider(provider)
        try:
            async with request.app.state.action_lock:
                plan, _ = await request.app.state.client.plan_edit(
                    resume_id, operations
                )
            return {"plan": plan.to_dict(), "persisted": False}
        except JobPlatformError as exc:
            translate_error(exc)
        except (ValueError, KeyError, IndexError, TypeError):
            raise HTTPException(422, "Invalid edit operations or field path") from None

    @app.patch(
        "/v1/{provider}/resumes/{resume_id}", dependencies=[Depends(authorize)]
    )
    async def save_resume(
        provider: str, resume_id: str, request: Request,
        operations: list[dict] = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        require_provider(provider)
        if not allow_experimental_writes:
            raise HTTPException(501, "104 write adapters require explicit opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match: <resumeTimestamp> is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters is required")
        expected_timestamp = if_match.strip('"')
        fingerprint = hashlib.sha256(json.dumps(
            {"timestamp":expected_timestamp,"operations":operations},
            ensure_ascii=False,sort_keys=True,separators=(",",":")
        ).encode("utf-8")).hexdigest()
        key = ("PATCH",provider,resume_id,idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(
                        409, "Save outcome is indeterminate; inspect before retrying"
                    )
                return cached["result"]
            try:
                plan, _ = await request.app.state.client.plan_edit(resume_id, operations)
                if str(plan.base_timestamp) != expected_timestamp:
                    raise HTTPException(412, "Resume has changed since the caller read it")
                # Reserve the key *before* any upstream write. A transport error
                # can occur after the remote server has committed the request.
                record = {"fingerprint": fingerprint, "state": "indeterminate"}
                request.app.state.idempotency_results[key] = record
                result = await request.app.state.client.save_edit(plan)
                record.update({"state": "succeeded", "result": result})
                return result
            except JobPlatformError as exc:
                translate_error(exc)
            except (ValueError,KeyError,IndexError,TypeError):
                raise HTTPException(422, "Invalid edit operations or field path") from None

    async def skill_operation_http(
        resume_id: str, request: Request, action: str, *,
        changes: dict | None, position: int | None,
        if_match: str | None, idempotency_key: str | None,
    ):
        # This route is intentionally 104-native, not a cross-provider schema.
        if not allow_experimental_writes:
            raise HTTPException(501, "104 SKILL writes require explicit opt-in")
        if if_match is None:
            raise HTTPException(428, 'If-Match: <resumeTimestamp> is required')
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters is required")
        expected = if_match.strip('"')
        data = {
            "action": action, "position": position,
            "changes": changes, "timestamp": expected,
        }
        fingerprint = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        key = ("SKILL", resume_id, idempotency_key)

        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(
                        409, "SKILL write outcome is indeterminate; inspect before retrying"
                    )
                return cached["result"]

            # All field/path validation and the caller's precondition must pass
            # before reserving the key and attempting a remote mutation.
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume has changed since caller's read")
                skill_operation_body(
                    before, action, changes=changes, position=position
                )
            except (ValueError, KeyError, TypeError, IndexError, UnsupportedWrite):
                raise HTTPException(
                    422, "Invalid SKILL field values or record position"
                ) from None
            except JobPlatformError as exc:
                translate_error(exc)

            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_skill(
                    resume_id, action, changes=changes, position=position,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/skills",
        dependencies=[Depends(authorize)],
    )
    async def create_skill(
        resume_id: str, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await skill_operation_http(
            resume_id, request, "create", changes=changes, position=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/skills/{position}",
        dependencies=[Depends(authorize)],
    )
    async def update_skill(
        resume_id: str, position: int, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await skill_operation_http(
            resume_id, request, "update", changes=changes, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/skills/{position}",
        dependencies=[Depends(authorize)],
    )
    async def delete_skill(
        resume_id: str, position: int, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await skill_operation_http(
            resume_id, request, "delete", changes=None, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    async def education_operation_http(
        resume_id: str, request: Request, action: str, *,
        changes: dict | None, position: int | None,
        if_match: str | None, idempotency_key: str | None,
    ):
        """104-specific EDUCATION CRUD, not a cross-provider data model."""
        if not allow_experimental_writes:
            raise HTTPException(501, "104 EDUCATION writes require explicit opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match: <resumeTimestamp> is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(
            json.dumps(
                {"action": action, "position": position, "changes": changes,
                 "timestamp": expected},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        key = ("EDUCATION", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(
                        409, "EDUCATION write outcome indeterminate; inspect before retrying"
                    )
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                education_operation_body(
                    before, action, changes=changes, position=position
                )
            except (ValueError, KeyError, TypeError, IndexError, UnsupportedWrite):
                raise HTTPException(
                    422, "Invalid EDUCATION fields or record position"
                ) from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_education(
                    resume_id, action, changes=changes, position=position,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/educations",
        dependencies=[Depends(authorize)],
    )
    async def create_education(
        resume_id: str, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await education_operation_http(
            resume_id, request, "create", changes=changes, position=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/educations/{position}",
        dependencies=[Depends(authorize)],
    )
    async def update_education(
        resume_id: str, position: int, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await education_operation_http(
            resume_id, request, "update", changes=changes, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/educations/{position}",
        dependencies=[Depends(authorize)],
    )
    async def delete_education(
        resume_id: str, position: int, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await education_operation_http(
            resume_id, request, "delete", changes=None, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    async def experience_operation_http(
        resume_id: str, request: Request, action: str, *,
        changes: dict | None, position: int | None,
        if_match: str | None, idempotency_key: str | None,
    ):
        """104-specific EXPERIENCE CRUD, not a cross-provider data model."""
        if not allow_experimental_writes:
            raise HTTPException(501, "104 EXPERIENCE writes require explicit opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match: <resumeTimestamp> is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(
            json.dumps(
                {"action": action, "position": position, "changes": changes,
                 "timestamp": expected},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        key = ("EXPERIENCE", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(
                        409, "EXPERIENCE write outcome indeterminate; inspect before retrying"
                    )
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                experience_operation_body(
                    before, action, changes=changes, position=position
                )
            except (ValueError, KeyError, TypeError, IndexError, UnsupportedWrite):
                raise HTTPException(
                    422, "Invalid EXPERIENCE fields or record position"
                ) from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_experience(
                    resume_id, action, changes=changes, position=position,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/experiences",
        dependencies=[Depends(authorize)],
    )
    async def create_experience(
        resume_id: str, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await experience_operation_http(
            resume_id, request, "create", changes=changes, position=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/experiences/{position}",
        dependencies=[Depends(authorize)],
    )
    async def update_experience(
        resume_id: str, position: int, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await experience_operation_http(
            resume_id, request, "update", changes=changes, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/experiences/{position}",
        dependencies=[Depends(authorize)],
    )
    async def delete_experience(
        resume_id: str, position: int, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await experience_operation_http(
            resume_id, request, "delete", changes=None, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    async def referrer_operation_http(
        resume_id: str, request: Request, action: str, *,
        changes: dict | None, position: int | None,
        if_match: str | None, idempotency_key: str | None,
    ):
        """104-specific REFERRER CRUD, not a cross-provider data model."""
        if not allow_experimental_writes:
            raise HTTPException(501, "104 REFERRER writes require explicit opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match: <resumeTimestamp> is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(
            json.dumps(
                {"action": action, "position": position, "changes": changes,
                 "timestamp": expected},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        key = ("REFERRER", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(
                        409, "REFERRER write outcome indeterminate; inspect before retrying"
                    )
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                form = before.get("referrer", {}).get("formData")
                if not isinstance(form, dict):
                    raise UnsupportedWrite("Missing REFERRER native form")
                options = None
                if action == "create" and not form:
                    options = request.app.state.client._data(
                        await request.app.state.client.transport.get_json(
                            "/profile/ajax/options"
                        )
                    )
                referrer_operation_body(
                    before, action, changes=changes, position=position,
                    options=options,
                )
            except (ValueError, KeyError, TypeError, IndexError, UnsupportedWrite):
                raise HTTPException(
                    422, "Invalid REFERRER fields or record position"
                ) from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_referrer(
                    resume_id, action, changes=changes, position=position,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/referrers",
        dependencies=[Depends(authorize)],
    )
    async def create_referrer(
        resume_id: str, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await referrer_operation_http(
            resume_id, request, "create", changes=changes, position=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/referrers/{position}",
        dependencies=[Depends(authorize)],
    )
    async def update_referrer(
        resume_id: str, position: int, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await referrer_operation_http(
            resume_id, request, "update", changes=changes, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/referrers/{position}",
        dependencies=[Depends(authorize)],
    )
    async def delete_referrer(
        resume_id: str, position: int, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await referrer_operation_http(
            resume_id, request, "delete", changes=None, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    async def project_operation_http(
        resume_id: str, request: Request, action: str, *,
        changes: dict | None, position: int | None,
        if_match: str | None, idempotency_key: str | None,
    ):
        """104-specific PROJECT CRUD, not a cross-provider data model."""
        if not allow_experimental_writes:
            raise HTTPException(501, "104 PROJECT writes require explicit opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match: <resumeTimestamp> is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(
            json.dumps(
                {"action": action, "position": position, "changes": changes,
                 "timestamp": expected},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        key = ("PROJECT", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(
                        409, "PROJECT write outcome indeterminate; inspect before retrying"
                    )
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                form = before.get("project", {}).get("formData")
                if not isinstance(form, dict):
                    raise UnsupportedWrite("Missing PROJECT native form")
                options = None
                if action == "create" and not form:
                    options = request.app.state.client._data(
                        await request.app.state.client.transport.get_json(
                            "/profile/ajax/options"
                        )
                    )
                project_operation_body(
                    before, action, changes=changes, position=position,
                    options=options,
                )
            except (ValueError, KeyError, TypeError, IndexError, UnsupportedWrite):
                raise HTTPException(
                    422, "Invalid PROJECT fields or record position"
                ) from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_project(
                    resume_id, action, changes=changes, position=position,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/projects",
        dependencies=[Depends(authorize)],
    )
    async def create_project(
        resume_id: str, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await project_operation_http(
            resume_id, request, "create", changes=changes, position=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/projects/{position}",
        dependencies=[Depends(authorize)],
    )
    async def update_project(
        resume_id: str, position: int, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await project_operation_http(
            resume_id, request, "update", changes=changes, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/projects/{position}",
        dependencies=[Depends(authorize)],
    )
    async def delete_project(
        resume_id: str, position: int, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await project_operation_http(
            resume_id, request, "delete", changes=None, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    async def portfolio_operation_http(
        resume_id: str, request: Request, *, action: str,
        position: int | None, changes: dict | None,
        if_match: str | None, idempotency_key: str | None,
    ):
        if not allow_experimental_writes:
            raise HTTPException(501, "104 PORTFOLIO create/delete requires experimental opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match resumeTimestamp is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(json.dumps(
            {"action": action, "position": position,
             "changes": changes, "timestamp": expected},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        key = ("PORTFOLIO", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(409, "PORTFOLIO deletion outcome indeterminate")
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                if action == "create":
                    if position is not None:
                        raise UnsupportedWrite("104 PORTFOLIO create has no position")
                    form = before.get("portfolio", {}).get("formData")
                    if not isinstance(form, dict):
                        raise UnsupportedWrite("104 PORTFOLIO form missing")
                    options = None
                    if not form:
                        options = request.app.state.client._data(
                            await request.app.state.client.transport.get_json(
                                "/profile/ajax/options"
                            )
                        )
                    portfolio_link_fields(before, changes, options=options)
                else:
                    if changes is not None:
                        raise UnsupportedWrite("104 PORTFOLIO delete has no fields")
                    portfolio_delete_body(before, position=position)
            except (ValueError, KeyError, TypeError, IndexError, UnsupportedWrite):
                raise HTTPException(422, "Invalid PORTFOLIO record position") from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_portfolio(
                    resume_id, action, position=position, changes=changes,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/portfolios",
        dependencies=[Depends(authorize)],
    )
    async def create_portfolio_link(
        resume_id: str, request: Request, changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await portfolio_operation_http(
            resume_id, request, action="create", position=None,
            changes=changes, if_match=if_match,
            idempotency_key=idempotency_key,
        )

    @app.get(
        "/v1/tw104/resumes/{resume_id}/portfolios/{position}/conversion",
        dependencies=[Depends(authorize)],
    )
    async def portfolio_conversion_status_http(
        resume_id: str,position: int,request: Request,
    ):
        """Read-only current FILE conversion, no signed preview URLs."""
        try:
            async with request.app.state.action_lock:
                return await request.app.state.client.get_portfolio_conversion_status(
                    resume_id,position=position,
                )
        except JobPlatformError as exc:
            translate_error(exc)

    @app.post(
        "/v1/tw104/resumes/{resume_id}/portfolio-files",
        dependencies=[Depends(authorize)],
    )
    async def upload_portfolio_file_http(
        resume_id: str, request: Request, file: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        """Local JSON/base64 upload; not a generic internet-facing file host."""
        if not allow_experimental_writes:
            raise HTTPException(501, "104 portfolio files require experimental opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match resumeTimestamp is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        if not isinstance(file, dict) or set(file) != {
            "name", "attachName", "filename", "contentType", "base64",
        }:
            raise HTTPException(422, "Expected title, attachment name and binary file")
        encoded = file["base64"]
        if (
            not isinstance(encoded, str)
            or not 12 <= len(encoded) <= ((MAX_BROWSER_UPLOAD_BYTES + 2) // 3) * 4
        ):
            raise HTTPException(422, "Portfolio file base64 exceeds supported size")
        try:
            raw = base64.b64decode(encoded, validate=True)
            upload = BrowserUpload(
                field_name="attachment", filename=file["filename"],
                content_type=file["contentType"], content=raw,
            )
            upload.validate()
        except (binascii.Error, ValueError, TypeError):
            raise HTTPException(422, "Invalid PORTFOLIO binary attachment") from None

        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(json.dumps({
            "name": file["name"], "attachName": file["attachName"],
            "filename": upload.filename, "contentType": upload.content_type,
            "sha256": hashlib.sha256(raw).hexdigest(), "timestamp": expected,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        key = ("PORTFOLIO_FILE", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused for different file")
                if cached["state"] != "succeeded":
                    raise HTTPException(409, "File outcome indeterminate; inspect first")
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since last read")
                form = before.get("portfolio", {}).get("formData")
                if not isinstance(form, dict):
                    raise UnsupportedWrite("104 PORTFOLIO formData missing")
                options = None
                if not form:
                    options = request.app.state.client._data(
                        await request.app.state.client.transport.get_json(
                            "/profile/ajax/options"
                        )
                    )
                portfolio_file_fields(
                    before, {"name": file["name"],
                             "attachName": file["attachName"]},
                    options=options,
                )
            except (KeyError, TypeError, ValueError, UnsupportedWrite):
                raise HTTPException(422, "Invalid PORTFOLIO file metadata") from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"state": "indeterminate", "fingerprint": fingerprint}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.upload_portfolio_file(
                    resume_id, expected_timestamp=expected,
                    name=file["name"], attach_name=file["attachName"],
                    filename=upload.filename, content_type=upload.content_type,
                    content=raw,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/portfolios/{position}",
        dependencies=[Depends(authorize)],
    )
    async def delete_portfolio(
        resume_id: str, position: int, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await portfolio_operation_http(
            resume_id, request, action="delete", position=position,
            changes=None, if_match=if_match, idempotency_key=idempotency_key,
        )

    async def language_operation_http(
        resume_id: str, request: Request, kind: str, action: str, *,
        changes: dict | None, position: int | None,
        if_match: str | None, idempotency_key: str | None,
    ):
        """104-specific LANGUAGE CRUD, not a cross-provider data model."""
        if kind not in LANGUAGE_KINDS:
            raise HTTPException(422, "Language kind must be local or foreign")
        if not allow_experimental_writes:
            raise HTTPException(501, "104 LANGUAGE writes require explicit opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match: <resumeTimestamp> is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(
            json.dumps(
                {"kind":kind, "action": action, "position": position, "changes": changes,
                 "timestamp": expected},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        key = ("LANGUAGE", resume_id, kind, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different payload")
                if cached["state"] != "succeeded":
                    raise HTTPException(
                        409, "LANGUAGE write outcome indeterminate; inspect before retrying"
                    )
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                language_operation_body(
                    before, kind, action, changes=changes, position=position
                )
                if action == "create":
                    fields = request.app.state.client._data(
                        await request.app.state.client.transport.get_json(
                            "/profile/ajax/inputField"
                        )
                    )
                    validate_language_capacity(
                        fields, kind, len(language_lists(before)[kind])
                    )
                if action != "delete":
                    # Validate current official options before reserving the
                    # Idempotency-Key. An invalid user selection is a definite
                    # preflight rejection, not an indeterminate remote write.
                    options = request.app.state.client._data(
                        await request.app.state.client.transport.get_json(
                            "/profile/ajax/options"
                        )
                    )
                    validate_language_selectors(options, kind, changes)
            except (ValueError, KeyError, TypeError, IndexError, UnsupportedWrite):
                raise HTTPException(
                    422, "Invalid LANGUAGE fields or record position"
                ) from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_language(
                    resume_id, kind, action, changes=changes, position=position,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/languages/{kind}",
        dependencies=[Depends(authorize)],
    )
    async def create_language(
        resume_id: str, kind: str, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await language_operation_http(
            resume_id, request, kind, "create", changes=changes, position=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/languages/{kind}/{position}",
        dependencies=[Depends(authorize)],
    )
    async def update_language(
        resume_id: str, kind: str, position: int, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await language_operation_http(
            resume_id, request, kind, "update", changes=changes, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/languages/{kind}/{position}",
        dependencies=[Depends(authorize)],
    )
    async def delete_language(
        resume_id: str, kind: str, position: int, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await language_operation_http(
            resume_id, request, kind, "delete", changes=None, position=position,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.put(
        "/v1/tw104/resumes/{resume_id}/themes/{section}",
        dependencies=[Depends(authorize)],
    )
    async def update_theme(
        resume_id: str, section: str, request: Request,
        body: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        if not allow_experimental_writes:
            raise HTTPException(501, "104 LAYOUT requires experimental write opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match resumeTimestamp is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        if section not in THEME_OPTION_KEYS or set(body) != {"selectedTheme"}:
            raise HTTPException(422, "Unsupported 104 theme request")
        value = body["selectedTheme"]
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(json.dumps(
            {"section": section, "value": value, "timestamp": expected},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        key = ("LAYOUT", resume_id, section, idempotency_key)
        async with request.app.state.action_lock:
            saved = request.app.state.idempotency_results.get(key)
            if saved is not None:
                if saved["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused for different theme")
                if saved["state"] != "succeeded":
                    raise HTTPException(409, "LAYOUT outcome indeterminate; inspect before retrying")
                return saved["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                options = request.app.state.client._data(
                    await request.app.state.client.transport.get_json("/profile/ajax/options")
                )
                theme_body(before, options, section, value)
            except (TypeError, ValueError, KeyError, UnsupportedWrite):
                raise HTTPException(422, "Invalid 104 theme option or section") from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.set_theme(
                    resume_id, section, value, expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.put(
        "/v1/tw104/resumes/{resume_id}/sort/{section}",
        dependencies=[Depends(authorize)],
    )
    async def sort_resume_records(
        resume_id: str, section: str, request: Request,
        body: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        if not allow_experimental_writes:
            raise HTTPException(501, "104 SORT requires experimental write opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match resumeTimestamp required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected_fields = (
            {"from", "to", "kind"} if section == "language"
            else {"from", "to"}
        )
        if section not in SORTABLE or set(body) != expected_fields:
            raise HTTPException(422, "Unsupported 104 sort request")
        kind = body.get("kind")
        if section == "language" and kind not in LANGUAGE_KINDS:
            raise HTTPException(422, "LANGUAGE sort requires local or foreign kind")
        source, target = body["from"], body["to"]
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(json.dumps(
            {"section": section, "kind": kind,
             "from": source, "to": target, "timestamp": expected},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        key = ("SORT", resume_id, section, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different sort")
                if cached["state"] != "succeeded":
                    raise HTTPException(409, "SORT outcome indeterminate; inspect before retrying")
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                sort_body(before, section, source, target, kind=kind)
            except (ValueError, TypeError, KeyError, UnsupportedWrite):
                raise HTTPException(422, "Invalid 104 sort positions") from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.sort_records(
                    resume_id, section, source, target,
                    kind=kind, expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    async def native_bio_action(
        resume_id: str, request: Request, action: str, *,
        changes: dict | None, if_match: str | None,
        idempotency_key: str | None,
    ):
        if not allow_experimental_writes:
            raise HTTPException(501, "104 BIO POST/DELETE requires experimental opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match resumeTimestamp is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(json.dumps(
            {"action": action, "changes": changes, "timestamp": expected},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        key = ("BIO_ACTION", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different BIO action")
                if cached["state"] != "succeeded":
                    raise HTTPException(409, "BIO action outcome indeterminate; inspect before retry")
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                bio_action_body(before, action, changes=changes)
            except (KeyError, TypeError, ValueError, UnsupportedWrite):
                raise HTTPException(422, "Invalid or unavailable native BIO action") from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_bio(
                    resume_id, action, changes=changes,
                    expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/biography",
        dependencies=[Depends(authorize)],
    )
    async def first_bio(
        resume_id: str, request: Request, changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await native_bio_action(
            resume_id, request, "create", changes=changes,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/biography",
        dependencies=[Depends(authorize)],
    )
    async def clear_bio(
        resume_id: str, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await native_bio_action(
            resume_id, request, "clear", changes=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    async def native_certificate_block_action(
        resume_id: str, request: Request, action: str, *,
        others: str | None, if_match: str | None,
        idempotency_key: str | None,
    ):
        if not allow_experimental_writes:
            raise HTTPException(501, "104 CERTIFICATE block writes require opt-in")
        if if_match is None:
            raise HTTPException(428, "If-Match resumeTimestamp is required")
        if not idempotency_key or len(idempotency_key) < 16:
            raise HTTPException(400, "Idempotency-Key of at least 16 characters required")
        expected = if_match.strip('"')
        fingerprint = hashlib.sha256(json.dumps(
            {"action": action, "others": others, "timestamp": expected},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        key = ("CERTIFICATE_BLOCK", resume_id, idempotency_key)
        async with request.app.state.action_lock:
            cached = request.app.state.idempotency_results.get(key)
            if cached is not None:
                if cached["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key reused with different certificate action")
                if cached["state"] != "succeeded":
                    raise HTTPException(409, "Certificate action result uncertain; inspect before retry")
                return cached["result"]
            try:
                before = await request.app.state.client.get_resume(resume_id)
                if str(before.get("resumeTimestamp")) != expected:
                    raise HTTPException(412, "Resume changed since caller's read")
                certificate_block_body(before, action, others=others)
            except (TypeError, KeyError, ValueError, UnsupportedWrite):
                raise HTTPException(422, "Invalid CERTIFICATE block action") from None
            except JobPlatformError as exc:
                translate_error(exc)
            record = {"fingerprint": fingerprint, "state": "indeterminate"}
            request.app.state.idempotency_results[key] = record
            try:
                result = await request.app.state.client.mutate_certificate_block(
                    resume_id, action, others=others, expected_timestamp=expected,
                )
            except JobPlatformError as exc:
                translate_error(exc)
            else:
                record.update({"state": "succeeded", "result": result})
                return result

    @app.post(
        "/v1/tw104/resumes/{resume_id}/certificate-block",
        dependencies=[Depends(authorize)],
    )
    async def initialize_certificate_block(
        resume_id: str, request: Request,
        changes: dict = Body(...),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        if set(changes) != {"others"}:
            raise HTTPException(422, "Expected the single others text field")
        return await native_certificate_block_action(
            resume_id, request, "initialize", others=changes["others"],
            if_match=if_match, idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/tw104/resumes/{resume_id}/certificate-block",
        dependencies=[Depends(authorize)],
    )
    async def clear_certificate_block(
        resume_id: str, request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return await native_certificate_block_action(
            resume_id, request, "clear", others=None,
            if_match=if_match, idempotency_key=idempotency_key,
        )

    return app
