"""Optional local FastAPI service using the same browser-backed 104 client.

Authentication is required for all routes other than /healthz.
No HTTP port is exposed publicly by default. The service runs one shared
browser session for its lifetime and serializes non-idempotent operations.
"""
from __future__ import annotations

import asyncio
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
            app.state.client = Resume104Client(session.page)
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
                "experimental_writable_sections": ["bio", "certificate"],
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

    return app
