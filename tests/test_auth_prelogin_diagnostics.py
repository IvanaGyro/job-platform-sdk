"""104 prelogin diagnostics: staged, safe, deterministic (no network)."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_platforms.core.errors import AuthenticationRequired
from job_platforms.providers.tw104.auth import (
    AuthConfig, FreshBrowserSession, _cloudflare_signal,
)


class FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {}


class FakeLocator:
    def __init__(self, page):
        self.page = page

    async def count(self):
        return int(self.page.url.startswith("https://signin.104.com.tw/"))


class FakePage:
    def __init__(
        self, nav_errors=None, nav_status=None, init_status=200,
        init_cf="unconfirmed",
    ):
        self.url = "about:blank"
        self.observers = {}
        self.nav_errors = nav_errors or {}
        self.nav_status = nav_status or {}
        self.init_status = init_status
        self.init_cf = init_cf

    def on(self, event, callback):
        self.observers[event] = callback

    async def goto(self, url, **_kwargs):
        self.url = url
        if url in self.nav_errors:
            raise RuntimeError(self.nav_errors[url])
        value = self.nav_status.get(url, FakeResponse())
        return value

    async def wait_for_timeout(self, _value):
        return None

    def locator(self, _selector):
        return FakeLocator(self)

    async def evaluate(self, _script):
        return {"status": self.init_status, "cloudflare": self.init_cf}


class FakeBrowser:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    async def launch_persistent_context(self, **_kwargs):
        return self.browser


class FakePlaywright:
    def __init__(self, browser):
        self.chromium = FakeChromium(browser)


class PreloginDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def check_failure(self, *, nav_status=None, nav_errors=None,
                            init_status=200, init_cf="unconfirmed"):
        with tempfile.TemporaryDirectory() as d:
            proxy_path = Path(d) / "proxy.txt"
            proxy_path.write_text("host.invalid:1234:fake-user:fake-password\n")
            cfg = AuthConfig("unused", str(proxy_path), proxy_priority=(1,))
            session = FreshBrowserSession(cfg)
            page = FakePage(
                nav_status=nav_status, nav_errors=nav_errors,
                init_status=init_status, init_cf=init_cf,
            )
            browser = FakeBrowser(page)
            session._pw = FakePlaywright(browser)
            with patch(
                "job_platforms.providers.tw104.auth._credentials",
                return_value={"A": "private-account", "P": "private-password"},
            ):
                with self.assertRaises(AuthenticationRequired) as err:
                    await session.open()
            message = str(err.exception)
            self.assertTrue(browser.closed)
            self.assertEqual(len(session.prelogin_diagnostics), 1)
            for secret in ("fake-password", "private-account", "private-password",
                           "host.invalid"):
                self.assertNotIn(secret, message)
            return session.prelogin_diagnostics[0], message

    def test_edge_header_is_not_proof_of_challenge(self):
        self.assertEqual(
            _cloudflare_signal({"CF-RAY": "example", "Server": "cloudflare"}),
            "edge_headers",
        )
        self.assertEqual(_cloudflare_signal({"Server": "nginx"}), "unconfirmed")
        self.assertEqual(
            _cloudflare_signal({"Cf-Mitigated": "challenge"}), "challenge",
        )

    async def test_navigation_403_cloudflare_challenge(self):
        p = "https://signin.104.com.tw/"
        diagnostic, message = await self.check_failure(
            nav_status={p: FakeResponse(403, {
                "cf-ray": "do-not-log-this-token", "cf-mitigated": "challenge",
            })}
        )
        self.assertEqual(diagnostic.stage, "signin_navigation")
        self.assertEqual(diagnostic.reason, "cloudflare_challenge")
        self.assertEqual(diagnostic.http_status, 403)
        self.assertEqual(diagnostic.cloudflare, "challenge")
        self.assertIn("status=403 cf=challenge", message)
        self.assertNotIn("do-not-log-this-token", message)

    async def test_login_init_403_cloudflare_headers_only(self):
        diagnostic, message = await self.check_failure(
            init_status=403, init_cf="edge_headers",
        )
        self.assertEqual(diagnostic.stage, "login_init")
        self.assertEqual(diagnostic.http_status, 403)
        self.assertEqual(diagnostic.cloudflare, "edge_headers")
        self.assertIn("login_init_http_error", message)

    async def test_navigation_403_without_cloudflare_is_unconfirmed(self):
        diagnostic, _ = await self.check_failure(nav_status={
            "https://pda.104.com.tw/work/peruseRecord/": FakeResponse(403)
        })
        self.assertEqual(diagnostic.stage, "pda_entry_navigation")
        self.assertEqual(diagnostic.http_status, 403)
        self.assertEqual(diagnostic.cloudflare, "unconfirmed")

    async def test_playwright_exception_does_not_leak_proxy_or_password(self):
        diagnostic, message = await self.check_failure(nav_errors={
            "https://pda.104.com.tw/work/peruseRecord/":
                "password=private-password proxy=host.invalid",
        })
        self.assertEqual(diagnostic.stage, "pda_entry_navigation")
        self.assertEqual(diagnostic.reason, "RuntimeError")
        self.assertIsNone(diagnostic.http_status)
        self.assertNotIn("private-password", message)

    async def test_network_error_code_extracted_without_url(self):
        diagnostic, message = await self.check_failure(nav_errors={
            "https://pda.104.com.tw/work/peruseRecord/":
                "net::ERR_TUNNEL_CONNECTION_FAILED via proxy="
                "http://fake-user:fake-password@host.invalid:1234",
        })
        self.assertEqual(diagnostic.stage, "pda_entry_navigation")
        self.assertEqual(
            diagnostic.network_error, "ERR_TUNNEL_CONNECTION_FAILED"
        )
        self.assertIn("net=ERR_TUNNEL_CONNECTION_FAILED", message)
        self.assertNotIn("host.invalid", message)
        self.assertNotIn("fake-password", message)

    async def test_http_200_with_explicit_cloudflare_challenge_is_rejected(self):
        diagnostic, _ = await self.check_failure(nav_status={
            "https://signin.104.com.tw/": FakeResponse(200, {
                "cf-mitigated": "challenge",
            })
        })
        self.assertEqual(diagnostic.reason, "cloudflare_challenge")
        self.assertEqual(diagnostic.http_status, 200)
        self.assertEqual(diagnostic.cloudflare, "challenge")

    async def test_login_init_200_with_challenge_is_rejected(self):
        diagnostic, _ = await self.check_failure(
            init_status=200, init_cf="challenge",
        )
        self.assertEqual(diagnostic.stage, "login_init")
        self.assertEqual(diagnostic.http_status, 200)
        self.assertEqual(diagnostic.cloudflare, "challenge")

    async def test_login_init_429_reported_not_assumed_cloudflare(self):
        diagnostic, _ = await self.check_failure(
            init_status=429, init_cf="unconfirmed",
        )
        self.assertEqual(diagnostic.http_status, 429)
        self.assertEqual(diagnostic.cloudflare, "unconfirmed")


if __name__ == "__main__":
    unittest.main()
