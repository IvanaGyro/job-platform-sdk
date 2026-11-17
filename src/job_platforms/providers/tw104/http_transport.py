"""Opt-in 104 HTTP transport: browser cookies + original login proxy, in memory.

No direct-IP fallback, implicit retry, or automatic writes. BrowserTransport
remains the reference and may be used independently.
"""
from __future__ import annotations
import asyncio
from typing import Any
from urllib.parse import urlencode, urlsplit
from job_platforms.core.errors import (
    AuthenticationRequired, ConflictError, UnsupportedWrite,
    UpstreamError, VerificationError,
)
from .transport import BrowserResponse, BrowserTransport, BrowserUpload

class CurlCffiTransport:
    ORIGIN = BrowserTransport.ORIGIN
    IMPERSONATE = "chrome146"

    def __init__(self, session: Any, *, allow_writes: bool = False):
        self._session = session
        self._allow_writes = allow_writes
        self._lock = asyncio.Lock()
        self._profile_version: str | None = None
        self._closed = False

    @classmethod
    def from_storage_state(
        cls, state: dict, *, proxy_url: str, user_agent: str,
        allow_writes: bool = False, session_factory: Any = None,
    ) -> "CurlCffiTransport":
        if not isinstance(proxy_url, str) or not proxy_url.startswith(
            ("http://", "https://", "socks5://", "socks5h://")
        ):
            raise ValueError("Explicit original login proxy is required")
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
            raise AuthenticationRequired("Browser storage state unavailable")
        from curl_cffi.requests import AsyncSession, Cookies
        cookies = Cookies()
        count = 0
        for item in state["cookies"]:
            if not isinstance(item, dict):
                continue
            domain = item.get("domain", "")
            host = domain.lstrip(".").lower() if isinstance(domain, str) else ""
            if host != "104.com.tw" and not host.endswith(".104.com.tw"):
                continue
            name, value = item.get("name"), item.get("value")
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            cookies.set(name, value, domain=domain, path=item.get("path") or "/",
                        secure=bool(item.get("secure", False)))
            count += 1
        if not count:
            raise AuthenticationRequired("No 104 cookies in browser session")
        if not isinstance(user_agent, str) or not user_agent:
            raise ValueError("Browser User-Agent is required")
        factory = session_factory or AsyncSession
        return cls(factory(
            impersonate=cls.IMPERSONATE, trust_env=False, proxy=proxy_url,
            cookies=cookies, headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://pda.104.com.tw/profile",
                "User-Agent": user_agent,
            },
        ), allow_writes=allow_writes)

    async def aclose(self):
        async with self._lock:
            if not self._closed:
                self._closed = True
                await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def request(
        self, method: str, path: str, *, params: dict | None = None,
        json_data: Any = None, form_data: dict | None = None,
        multipart_fields: dict[str, str] | None = None,
        multipart_upload: BrowserUpload | None = None,
    ) -> BrowserResponse:
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Unsupported HTTP method")
        path = BrowserTransport._path(path)
        if sum(x is not None for x in (json_data, form_data, multipart_fields)) > 1:
            raise ValueError("Choose exactly one HTTP request body type")
        if multipart_fields is not None and (
            method != "POST" or not isinstance(multipart_fields, dict)
            or (not multipart_fields and multipart_upload is None)
            or any(not isinstance(k, str) or not isinstance(v, str)
                   for k, v in multipart_fields.items())
        ):
            raise ValueError("104 multipart fields require POST and text values")
        if multipart_upload is not None:
            if (method != "POST" or multipart_fields is None
                or json_data is not None or form_data is not None
                or not isinstance(multipart_upload, BrowserUpload)):
                raise ValueError("Binary attachment requires multipart POST")
            multipart_upload.validate()
            if multipart_upload.field_name == "convertPreviewThumbnail" and (
                path != "/api/resumes/files/convert-preview-thumbnail"
                or multipart_fields
            ):
                raise ValueError("Invalid 104 conversion multipart endpoint")
            if multipart_upload.field_name == "attachment" and (
                path != "/profile/ajax/resumeByBlock/portfolio"
            ):
                raise ValueError("Invalid 104 attachment endpoint")
        if self._closed:
            raise AuthenticationRequired("104 HTTP transport closed")
        write = method != "GET"
        if write and not self._allow_writes:
            raise UnsupportedWrite("104 HTTP writes require explicit opt-in")
        async with self._lock:
            if self._closed:
                raise AuthenticationRequired("104 HTTP transport closed")
            if write and not self._profile_version:
                raise VerificationError("104-profile-ver not observed on GET; not submitted")
            headers = {}
            if write:
                headers["104-profile-ver"] = self._profile_version
            kwargs = {
                "params": params, "headers": headers,
                "allow_redirects": False, "timeout": 30,
            }
            if json_data is not None:
                kwargs["json"] = json_data
            elif form_data is not None:
                kwargs["data"] = urlencode(form_data, doseq=True)
                headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
            mime = None
            if multipart_fields is not None:
                # curl_cffi does not support requests' files= API. Use
                # CurlMime even for text-only FormData: 104 PORTFOLIO LINK
                # needs multipart/form-data without a file.
                from curl_cffi import CurlMime
                mime = CurlMime()
                try:
                    for key, value in multipart_fields.items():
                        mime.addpart(name=key, data=value.encode("utf-8"))
                    if multipart_upload is not None:
                        mime.addpart(
                            name=multipart_upload.field_name,
                            content_type=multipart_upload.content_type,
                            filename=multipart_upload.filename,
                            data=multipart_upload.content,
                        )
                except Exception:
                    mime.close()
                    raise ValueError("Failed to prepare multipart upload") from None
                kwargs["multipart"] = mime
            try:
                try:
                    response = await self._session.request(
                        method, self.ORIGIN + path, **kwargs,
                    )
                except Exception:
                    # A raw curl exception might contain credential-bearing proxy URL.
                    if write:
                        raise VerificationError(
                            "104 HTTP write outcome unknown; inspect before retrying"
                        ) from None
                    raise UpstreamError(urlsplit(path).path, 0) from None
            finally:
                if mime is not None:
                    mime.close()
            status = response.status_code
            # A 409/412 is an explicit concurrency refusal, never a success.
            # 104's specific conflict status codes are not yet live-proven.
            if write and status in (409, 412):
                raise ConflictError(
                    "104 rejected write with revision/conflict response"
                )
            if status in (401, 403) or 300 <= status < 400:
                if write:
                    raise VerificationError(
                        "104 write received auth or redirect response; "
                        "inspect before retrying"
                    )
                raise AuthenticationRequired(
                    "104 rejected HTTP session: login or IP/network risk"
                )
            if not 200 <= status < 300:
                if write and (status == 429 or status >= 500):
                    raise VerificationError(
                        "104 write returned a transient/server error; "
                        "inspect before retrying"
                    )
                raise UpstreamError(urlsplit(path).path, status)
            version = response.headers.get("104-profile-ver")
            if version:
                self._profile_version = version
            content_type = response.headers.get("content-type", "").split(";")[0].lower()
            if content_type != "application/json" and not content_type.endswith("+json"):
                if write:
                    raise VerificationError(
                        "104 write returned non-JSON; inspect before retrying"
                    )
                raise UpstreamError(urlsplit(path).path, status)
            try:
                data = response.json()
            except (ValueError, TypeError):
                if write:
                    raise VerificationError(
                        "104 write returned malformed JSON; inspect before retrying"
                    ) from None
                raise UpstreamError(urlsplit(path).path, status) from None
            if data is None:
                if write:
                    raise VerificationError(
                        "104 write response omitted JSON; inspect before retrying"
                    )
                raise UpstreamError(urlsplit(path).path, status)
            return BrowserResponse(status=status, content_type=content_type, data=data)

    async def get_json(self, path: str, *, params: dict | None = None) -> Any:
        return (await self.request("GET", path, params=params)).data

    async def put_json(self, path: str, data: Any, *, params: dict | None = None) -> Any:
        return (await self.request("PUT", path, json_data=data, params=params)).data

    async def ensure_authenticated(self) -> bool:
        try:
            data = await self.get_json("/profile/ajax/overview")
            return isinstance(
                data.get("data", {}).get("formData", {}).get("overview"), list
            )
        except (AuthenticationRequired, UpstreamError, AttributeError):
            return False
