"""Synthetic lifecycle tests for opt-in login-only Chromium; no network."""
import unittest
from unittest.mock import patch

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.providers.tw104.auth import AuthConfig, FreshBrowserSession
from job_platforms.providers.tw104.http_transport import CurlCffiTransport


class FakeContext:
    def __init__(self):
        self.closed = False
    async def storage_state(self):
        return {"cookies": [{"name": "synthetic", "value": "test",
                             "domain": ".104.com.tw"}]}
    async def close(self):
        self.closed = True


class FakePage:
    async def evaluate(self, arg):
        assert arg == "navigator.userAgent"
        return "Synthetic-Browser-UA"


class FakeProfile:
    def __init__(self):
        self.cleaned = False
    def cleanup(self):
        self.cleaned = True


class FakePlaywright:
    def __init__(self):
        self.stopped = False
    async def stop(self):
        self.stopped = True


class FakeTransport:
    def __init__(self):
        self.closed = False
    async def aclose(self):
        self.closed = True


class DetachTests(unittest.IsolatedAsyncioTestCase):
    def instance(self):
        session = FreshBrowserSession(AuthConfig("synthetic-only", "synthetic-only"))
        session._context = FakeContext()
        session.page = FakePage()
        session._profile = FakeProfile()
        session._pw = FakePlaywright()
        session._proxy_url = "http://proxy.invalid:1234"
        return session

    async def test_detached_closes_browser_only_after_successful_handoff(self):
        session = self.instance()
        context, profile, driver = session._context, session._profile, session._pw
        transport = FakeTransport()
        with patch.object(CurlCffiTransport, "from_storage_state",
                          return_value=transport) as handoff:
            client = await session.resume_client(transport="curl_cffi_detached")
        self.assertIs(client.transport, transport)
        self.assertIsNone(client.page)
        self.assertIsNone(session.page)
        self.assertTrue(context.closed)
        self.assertTrue(profile.cleaned)
        self.assertTrue(driver.stopped)
        self.assertIsNone(session._context)
        self.assertEqual(handoff.call_args.kwargs["user_agent"], "Synthetic-Browser-UA")
        with self.assertRaises(UnsupportedWrite):
            await client.create_resume()
        await session.__aexit__(None, None, None)
        self.assertTrue(transport.closed)

    async def test_non_detached_keeps_browser_available(self):
        session = self.instance()
        context = session._context
        transport = FakeTransport()
        with patch.object(CurlCffiTransport, "from_storage_state",
                          return_value=transport):
            client = await session.resume_client(transport="curl_cffi")
        self.assertIs(client.page, session.page)
        self.assertFalse(context.closed)
        await session.__aexit__(None, None, None)
        self.assertTrue(context.closed)
        self.assertTrue(transport.closed)

    async def test_failed_handoff_does_not_close_browser(self):
        session = self.instance()
        context, profile, driver = session._context, session._profile, session._pw
        with patch.object(CurlCffiTransport, "from_storage_state",
                          side_effect=RuntimeError("synthetic construction failed")):
            with self.assertRaises(RuntimeError):
                await session.resume_client(transport="curl_cffi_detached")
        self.assertIs(session._context, context)
        self.assertFalse(context.closed)
        self.assertFalse(profile.cleaned)
        self.assertFalse(driver.stopped)
        await session.__aexit__(None, None, None)

    async def test_bad_transport_rejected_without_side_effects(self):
        session = self.instance()
        with self.assertRaises(ValueError):
            await session.resume_client(transport="invalid")
        self.assertFalse(session._context.closed)
        await session.__aexit__(None, None, None)


if __name__ == "__main__":
    unittest.main()
