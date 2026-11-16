"""104 requests run inside the already-authenticated browser's same origin.

Direct curl-cffi with browser cookies returned 403 from some My104 endpoints.
The browser context, rather than external cookies, is the reference transport.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

from job_platforms.core.errors import AuthenticationRequired, UpstreamError


@dataclass
class BrowserResponse:
    status: int
    content_type: str
    data: Any


class BrowserTransport:
    ORIGIN = "https://pda.104.com.tw"

    def __init__(self, page: Any):
        self.page = page
        self._lock = asyncio.Lock()

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
    ) -> BrowserResponse:
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Unsupported HTTP method")
        if json_data is not None and form_data is not None:
            raise ValueError("Choose form or JSON body")
        path = self._path(path)
        if params:
            path += ("&" if "?" in path else "?") + urlencode(params, doseq=True)
        async with self._lock:
            if urlsplit(self.page.url).hostname != "pda.104.com.tw":
                raise AuthenticationRequired("Browser is not on authenticated My104")
            response = await self.page.evaluate(
                """async arg => {
                    const url = new URL(arg.path, location.origin);
                    if (url.origin !== 'https://pda.104.com.tw') {
                        throw Error('Cross-origin request prohibited');
                    }
                    const headers = {Accept: 'application/json, text/plain, */*'};
                    let body;
                    if (arg.json !== null) {
                        headers['Content-Type'] = 'application/json';
                        body = JSON.stringify(arg.json);
                    } else if (arg.form !== null) {
                        headers['Content-Type'] =
                            'application/x-www-form-urlencoded;charset=UTF-8';
                        body = new URLSearchParams(arg.form).toString();
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
                    return {status:r.status, content_type:type, data};
                }""",
                {"path": path, "method": method,
                 "json": json_data, "form": form_data},
            )
        if response["status"] in (401, 403):
            raise AuthenticationRequired("104 browser authentication expired")
        if not 200 <= response["status"] < 300 or response["data"] is None:
            # Do not include query parameters or response bodies in errors.
            raise UpstreamError(urlsplit(path).path, response["status"])
        return BrowserResponse(**response)

    async def get_json(self, path: str, *, params: dict | None = None) -> Any:
        return (await self.request("GET", path, params=params)).data

    async def ensure_authenticated(self) -> bool:
        try:
            data = await self.get_json("/profile/ajax/overview")
            return isinstance(
                data.get("data", {}).get("formData", {}).get("overview"), list
            )
        except (AuthenticationRequired, UpstreamError, AttributeError):
            return False
