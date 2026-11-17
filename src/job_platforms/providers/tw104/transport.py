"""104 requests run inside the already-authenticated browser's same origin.

Direct curl-cffi with browser cookies returned 403 from some My104 endpoints.
The browser context, rather than external cookies, is the reference transport.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

from job_platforms.core.errors import AuthenticationRequired, UpstreamError


@dataclass
class BrowserResponse:
    status: int
    content_type: str
    data: Any


MAX_BROWSER_UPLOAD_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class BrowserUpload:
    """One bounded multipart file; browser sends it without local storage."""
    field_name: str
    filename: str
    content_type: str
    content: bytes

    def validate(self) -> None:
        if (
            self.field_name not in {"attachment", "convertPreviewThumbnail"}
            or not isinstance(self.filename, str)
            or not self.filename
            or len(self.filename) > 120
            or any(ch in self.filename for ch in ("/", "\\", "\x00", "\r", "\n"))
            or not isinstance(self.content_type, str)
            or self.content_type not in {
                "application/pdf", "image/png", "image/jpeg",
            }
            or not isinstance(self.content, bytes)
            or not 8 <= len(self.content) <= MAX_BROWSER_UPLOAD_BYTES
        ):
            raise ValueError("Unsupported browser multipart file")
        ext = self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""
        match = {
            "application/pdf": {"pdf"},
            "image/png": {"png"},
            "image/jpeg": {"jpg", "jpeg"},
        }
        if ext not in match[self.content_type]:
            raise ValueError("Multipart file name and MIME type do not match")
        if self.content_type == "application/pdf" and not (
            self.content.startswith(b"%PDF-") and b"%%EOF" in self.content[-64:]
        ):
            raise ValueError("Invalid PDF file signature or trailer")
        if self.content_type == "image/png" and not self.content.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            raise ValueError("Invalid PNG signature")
        if self.content_type == "image/jpeg" and not (
            self.content[:3] == b"\xff\xd8\xff"
            and self.content.endswith(b"\xff\xd9")
        ):
            raise ValueError("Invalid JPEG file signature")


class BrowserTransport:
    ORIGIN = "https://pda.104.com.tw"

    def __init__(self, page: Any):
        self.page = page
        self._lock = asyncio.Lock()
        # 104's official frontend copies the 104-profile-ver response header
        # into each subsequent PUT/POST/DELETE request. Keep it in memory only.
        self._profile_version: str | None = None

    @staticmethod
    def _path(path: str) -> str:
        parts = urlsplit(path)
        if not path.startswith("/") or path.startswith("//") or parts.scheme or parts.netloc:
            raise ValueError("Only relative My104 paths are permitted")
        if "#" in path:
            raise ValueError("URL fragments are not permitted")
        return path

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_data: Any = None,
        form_data: dict | None = None,
        multipart_fields: dict[str, str] | None = None,
        multipart_upload: BrowserUpload | None = None,
    ) -> BrowserResponse:
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Unsupported HTTP method")
        if sum(x is not None for x in (
            json_data, form_data, multipart_fields,
        )) > 1:
            raise ValueError("Choose exactly one HTTP request body type")
        if multipart_fields is not None and (
            method != "POST"
            or not isinstance(multipart_fields, dict)
            or (not multipart_fields and multipart_upload is None)
            or any(not isinstance(k, str) or not isinstance(v, str)
                   for k, v in multipart_fields.items())
        ):
            raise ValueError("104 multipart fields require POST and text values")
        if multipart_upload is not None:
            if method != "POST" or multipart_fields is None or (
                json_data is not None or form_data is not None
            ) or not isinstance(multipart_upload, BrowserUpload):
                raise ValueError("Binary attachment requires multipart POST")
            multipart_upload.validate()
            if multipart_upload.field_name == "convertPreviewThumbnail" and (
                path != "/api/resumes/files/convert-preview-thumbnail"
                or multipart_fields
            ):
                raise ValueError("104 preview conversion accepts only a conversion File")
            if multipart_upload.field_name == "attachment" and (
                path != "/profile/ajax/resumeByBlock/portfolio"
            ):
                raise ValueError("104 resume attachment path is invalid")
        path = self._path(path)
        if params:
            path += ("&" if "?" in path else "?") + urlencode(params, doseq=True)
        async with self._lock:
            if urlsplit(self.page.url).hostname != "pda.104.com.tw":
                raise AuthenticationRequired("Browser is not on authenticated My104")
            if method in ("POST", "PUT", "DELETE") and not self._profile_version:
                from job_platforms.core.errors import VerificationError
                raise VerificationError(
                    "104-profile-ver was not observed on a prior GET response; "
                    "write request not submitted"
                )
            response = await self.page.evaluate(
                """async arg => {
                    const url = new URL(arg.path, location.origin);
                    if (url.origin !== 'https://pda.104.com.tw') {
                        throw Error('Cross-origin request prohibited');
                    }
                    const headers = {Accept: 'application/json, text/plain, */*'};
                    if (['PUT','POST','DELETE'].includes(arg.method)) {
                        headers['104-profile-ver'] = arg.profile_version;
                    }
                    let body;
                    if (arg.json !== null) {
                        headers['Content-Type'] = 'application/json';
                        body = JSON.stringify(arg.json);
                    } else if (arg.form !== null) {
                        headers['Content-Type'] =
                            'application/x-www-form-urlencoded;charset=UTF-8';
                        body = new URLSearchParams(arg.form).toString();
                    }
                    if (arg.multipart !== null) {
                        // Browser sets the multipart/form-data boundary itself.
                        // Never manually supply a Content-Type with FormData.
                        body = new FormData();
                        for (const [key, value] of Object.entries(arg.multipart)) {
                            body.append(key, value);
                        }
                        if (arg.file !== null) {
                            // The browser builds the File and boundary in
                            // memory. The attachment is never written to a
                            // browser-visible disk file or logged.
                            const decoded = atob(arg.file.base64);
                            const bytes = new Uint8Array(decoded.length);
                            for (let i = 0; i < decoded.length; i++) {
                                bytes[i] = decoded.charCodeAt(i);
                            }
                            const file = new File(
                                [bytes], arg.file.filename,
                                {type: arg.file.content_type}
                            );
                            body.append(arg.file.field_name, file, file.name);
                        }
                    }
                    const r = await fetch(url, {
                        method: arg.method, headers, body,
                        credentials: 'include', redirect: 'follow'
                    });
                    const type = (r.headers.get('content-type')||'').split(';')[0];
                    const text = await r.text();
                    let data = null;
                    if (type.includes('json')) {
                        try { data = JSON.parse(text); } catch(e) {}
                    }
                    return {status:r.status, content_type:type, data,
                            profile_version:r.headers.get('104-profile-ver')};
                }""",
                {"path": path, "method": method,
                 "json": json_data, "form": form_data,
                 "multipart": multipart_fields,
                 "file": ({
                     "field_name": multipart_upload.field_name,
                     "filename": multipart_upload.filename,
                     "content_type": multipart_upload.content_type,
                     "base64": base64.b64encode(multipart_upload.content).decode("ascii"),
                 } if multipart_upload is not None else None),
                 "profile_version": self._profile_version},
            )
            if response.get("profile_version"):
                self._profile_version = response["profile_version"]
        if response["status"] in (401, 403):
            raise AuthenticationRequired("104 browser authentication expired")
        if not 200 <= response["status"] < 300 or response["data"] is None:
            # Do not include query parameters or response bodies in errors.
            raise UpstreamError(urlsplit(path).path, response["status"])
        return BrowserResponse(
            status=response["status"],
            content_type=response["content_type"],
            data=response["data"],
        )

    async def get_json(self, path: str, *, params: dict | None = None) -> Any:
        return (await self.request("GET", path, params=params)).data

    async def put_json(self, path: str, data: Any, *, params: dict | None = None) -> Any:
        return (await self.request("PUT", path, params=params, json_data=data)).data

    async def ensure_authenticated(self) -> bool:
        try:
            data = await self.get_json("/profile/ajax/overview")
            return isinstance(
                data.get("data", {}).get("formData", {}).get("overview"), list
            )
        except (AuthenticationRequired, UpstreamError, AttributeError):
            return False
