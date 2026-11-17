"""Manual browser integration: verify 104-style multipart bytes entirely offline.

Run from repository root:
  PYTHONPATH=src xvfb-run -a python tests/integration_browser_multipart.py

This intercepts all https://pda.104.com.tw requests inside a synthetic
Chromium profile. No real network, credentials, resume or 104 account
is involved. The goal is proving FormData headers, FILE part and binary
bytes, beyond a mocked page.evaluate source-string assertion.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from patchright.async_api import async_playwright

from job_platforms.providers.tw104.portfolio_records import portfolio_file_fields
from job_platforms.providers.tw104.transport import BrowserTransport, BrowserUpload

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
DOC = {
    "portfolio": {
        "formData": {
            "themeChoose": {"selectedTheme": {
                "name": "Synthetic theme", "text": "Synthetic", "value": 1,
            }},
            "portfolios": [],
        }
    }
}


async def main():
    captured = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = await browser.new_page()
            async def intercept(route):
                req = route.request
                if req.method == "POST":
                    headers = await req.all_headers()
                    raw = req.post_data_buffer
                    assert raw is not None
                    ctype = headers.get("content-type", "")
                    assert ctype.startswith("multipart/form-data; boundary=")
                    boundary = ctype.split("boundary=", 1)[1]
                    assert boundary.encode("ascii") in raw
                    assert b'name="attachment"; filename="synthetic.pdf"' in raw
                    assert b"name=\"blockValueList[portfolio][attachType]\"" in raw
                    assert PDF in raw
                    assert headers.get("104-profile-ver") == "synthetic-profile-version"
                    captured.append({
                        "file_part_found": True,
                        "header_verified": True,
                        "bytes_match": True,
                    })
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        headers={"104-profile-ver": "synthetic-profile-updated"},
                        body='{"data":{"ok":true}}',
                    )
                else:
                    await route.fulfill(
                        status=200, content_type="text/html",
                        body="<html><body>Offline test page</body></html>",
                    )
            await page.route("https://pda.104.com.tw/**", intercept)
            await page.goto(
                "https://pda.104.com.tw/profile",
                wait_until="domcontentloaded",
            )
            transport = BrowserTransport(page)
            transport._profile_version = "synthetic-profile-version"
            result = await transport.request(
                "POST", "/profile/ajax/resumeByBlock/portfolio",
                params={"vno": "synthetic"},
                multipart_fields=portfolio_file_fields(
                    DOC, {"name": "Synthetic Upload",
                          "attachName": "synthetic.pdf"}
                ),
                multipart_upload=BrowserUpload(
                    "attachment", "synthetic.pdf",
                    "application/pdf", PDF,
                ),
            )
            assert result.status == 200 and len(captured) == 1
            assert transport._profile_version == "synthetic-profile-updated"
            print("BROWSER_MULTIPART_BINARY_WIRE: PASS")
            print("NO_NETWORK_TO_REAL_104: PASS")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
