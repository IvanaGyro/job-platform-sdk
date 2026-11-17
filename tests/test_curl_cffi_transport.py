"""Synthetic curl_cffi transport tests: no real credentials, proxy or network."""
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys
from job_platforms.core.errors import (
    AuthenticationRequired, UnsupportedWrite, UpstreamError, VerificationError,
)
from job_platforms.providers.tw104.http_transport import CurlCffiTransport
from job_platforms.providers.tw104.transport import BrowserUpload
from job_platforms.providers.tw104.client import Resume104Client

class Reply:
    def __init__(self, status=200, data=None, content_type="application/json",
                 version=None):
        self.status_code = status
        self._data = data if data is not None else {"data": {}}
        self.headers = {"content-type": content_type}
        if version:
            self.headers["104-profile-ver"] = version
    def json(self):
        return self._data

class Session:
    def __init__(self, replies=(), error=None):
        self.replies = iter(replies)
        self.error = error
        self.calls = []
        self.closed = False
    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return next(self.replies)
    async def close(self):
        self.closed = True

class CurlTransportTests(unittest.IsolatedAsyncioTestCase):
    def transport(self, replies=(), **kw):
        session = Session(replies)
        return CurlCffiTransport(session, **kw), session

    async def test_get_read_response_and_version(self):
        t, s = self.transport([Reply(data={"data":{"formData":{"overview":[]}}},
                                     version="synthetic-v1")])
        self.assertEqual(len(await Resume104Client(transport=t).list_resumes()), 0)
        self.assertEqual(t._profile_version, "synthetic-v1")
        self.assertEqual(s.calls[0][1], "https://pda.104.com.tw/profile/ajax/overview")
        self.assertFalse(s.calls[0][2]["allow_redirects"])

    async def test_path_guard_prevents_cross_origin(self):
        t, s = self.transport()
        for path in ["https://example.invalid/", "//example.invalid/", "/path#fragment"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                await t.get_json(path)
        self.assertEqual(s.calls, [])

    async def test_reject_expired_or_blocked_or_redirect(self):
        for code in (401, 403, 302):
            with self.subTest(code=code):
                t, _ = self.transport([Reply(status=code)])
                with self.assertRaises(AuthenticationRequired):
                    await t.get_json("/profile/ajax/overview")

    async def test_non_json_and_failed_response(self):
        for response in (Reply(content_type="text/html"), Reply(status=500)):
            t, _ = self.transport([response])
            with self.assertRaises(UpstreamError):
                await t.get_json("/profile/ajax/overview")

    async def test_get_network_failure_is_sanitized(self):
        t = CurlCffiTransport(Session(error=RuntimeError("proxy-user:password")))
        with self.assertRaises(UpstreamError) as err:
            await t.get_json("/profile/ajax/overview")
        self.assertNotIn("password", str(err.exception))

    async def test_write_disabled_by_default(self):
        t, s = self.transport()
        with self.assertRaises(UnsupportedWrite):
            await t.request("POST", "/profile/ajax/resumeByBlock/bio", json_data={})
        self.assertFalse(s.calls)

    async def test_write_must_first_receive_version_header(self):
        t, s = self.transport(allow_writes=True)
        with self.assertRaises(VerificationError):
            await t.put_json("/profile/ajax/resumeByBlock/bio", {})
        self.assertFalse(s.calls)

    async def test_write_forwards_version_and_updates_it(self):
        t, s = self.transport([Reply(version="v1"), Reply(version="v2"),
                               Reply(version="v3")], allow_writes=True)
        await t.get_json("/profile/ajax/overview")
        await t.request("PUT", "/profile/ajax/resumeByBlock/bio", json_data={"synthetic":1})
        await t.request("DELETE", "/profile/ajax/resumeByBlock/skill",
                        params={"vno":"test"})
        self.assertEqual(s.calls[1][2]["headers"]["104-profile-ver"], "v1")
        self.assertEqual(s.calls[2][2]["headers"]["104-profile-ver"], "v2")
        self.assertEqual(t._profile_version, "v3")

    async def test_ambiguous_write_never_retries(self):
        s = Session([Reply(version="v1")])
        t = CurlCffiTransport(s, allow_writes=True)
        await t.get_json("/profile/ajax/overview")
        s.error = RuntimeError("private proxy credential")
        with self.assertRaises(VerificationError) as err:
            await t.put_json("/profile/ajax/resumeByBlock/bio", {})
        self.assertNotIn("credential", str(err.exception))
        self.assertEqual(len(s.calls), 2)

    async def test_form_encoding(self):
        t,s = self.transport([Reply(version="v1"),Reply()],allow_writes=True)
        await t.get_json("/profile/ajax/overview")
        await t.request("POST", "/profile/ajax/resumeByBlock/bio",
                        form_data={"native field":"a&b"})
        self.assertEqual(s.calls[1][2]["data"],"native+field=a%26b")
        self.assertIn("urlencoded",s.calls[1][2]["headers"]["Content-Type"])

    async def test_close_and_no_request_after_close(self):
        t,s=self.transport()
        await t.aclose()
        self.assertTrue(s.closed)
        with self.assertRaises(AuthenticationRequired):
            await t.get_json("/profile/ajax/overview")

    async def test_cookie_scope_and_explicit_proxy(self):
        captured = {}
        def factory(**kw):
            captured.update(kw)
            return Session()
        state={"cookies":[
            {"name":"one","value":"synthetic","domain":".104.com.tw","path":"/"},
            {"name":"other","value":"not-copied","domain":".example.invalid"},
        ]}
        with self.assertRaises(ValueError):
            CurlCffiTransport.from_storage_state(
                state,proxy_url="",user_agent="synthetic",session_factory=factory)
        # A synthetic fake for the *optional* curl_cffi extra keeps the
        # base-package CI able to exercise cookie scope and proxy wiring.
        class FakeCookies:
            def __init__(self):
                self.jar = []
            def set(self, name, value, domain="", path="/", secure=False):
                self.jar.append(SimpleNamespace(
                    name=name, value=value, domain=domain,
                    path=path, secure=secure,
                ))
        fake_module = ModuleType("curl_cffi.requests")
        fake_module.Cookies = FakeCookies
        fake_module.AsyncSession = factory
        fake_parent = ModuleType("curl_cffi")
        fake_parent.__path__ = []
        with patch.dict(sys.modules, {
            "curl_cffi": fake_parent,
            "curl_cffi.requests": fake_module,
        }):
            t=CurlCffiTransport.from_storage_state(
                state,proxy_url="http://user:pass@proxy.invalid:9999",
                user_agent="synthetic",session_factory=factory)
        self.assertEqual(captured["impersonate"],"chrome146")
        self.assertEqual(captured["proxy"],"http://user:pass@proxy.invalid:9999")
        self.assertFalse(captured["trust_env"])
        self.assertEqual(len(captured["cookies"].jar),1)
        await t.aclose()

    async def test_multipart_uses_curlmime_and_closes_native_resource(self):
        class FakeMime:
            instances = []
            def __init__(self):
                self.parts = []
                self.closed = False
                self.instances.append(self)
            def addpart(self, **kwargs):
                self.parts.append(kwargs)
            def close(self):
                self.closed = True
        fake_cffi = ModuleType("curl_cffi")
        fake_cffi.CurlMime = FakeMime
        fake_cffi.__path__ = []
        sample = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
        t, session = self.transport([Reply(version="v1"), Reply()],
                                    allow_writes=True)
        await t.get_json("/profile/ajax/overview")
        upload = BrowserUpload("attachment", "synthetic.pdf",
                               "application/pdf", sample)
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi}):
            await t.request("POST", "/profile/ajax/resumeByBlock/portfolio",
                            multipart_fields={"blockValueList[portfolio][attachType]": "1"},
                            multipart_upload=upload)
        method, url, kwargs = session.calls[1]
        self.assertEqual(method, "POST")
        self.assertNotIn("files", kwargs)
        self.assertIs(kwargs["multipart"], FakeMime.instances[0])
        self.assertTrue(kwargs["multipart"].closed)
        self.assertEqual(len(kwargs["multipart"].parts), 2)
        self.assertEqual(kwargs["multipart"].parts[0]["name"],
                         "blockValueList[portfolio][attachType]")
        self.assertEqual(kwargs["multipart"].parts[0]["data"], b"1")
        self.assertEqual(kwargs["multipart"].parts[1]["data"], sample)
        self.assertEqual(kwargs["multipart"].parts[1]["filename"], "synthetic.pdf")
        self.assertNotIn("data", kwargs)
        self.assertNotIn("Content-Type", kwargs["headers"])

    async def test_multipart_link_without_file_is_still_formdata(self):
        class FakeMime:
            instances = []
            def __init__(self):
                self.parts = []
                self.closed = False
                self.instances.append(self)
            def addpart(self, **kwargs):
                self.parts.append(kwargs)
            def close(self):
                self.closed = True
        fake_cffi = ModuleType("curl_cffi")
        fake_cffi.CurlMime = FakeMime
        fake_cffi.__path__ = []
        t, session = self.transport([Reply(version="v1"), Reply()],
                                    allow_writes=True)
        await t.get_json("/profile/ajax/overview")
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi}):
            await t.request("POST", "/profile/ajax/resumeByBlock/portfolio",
                            multipart_fields={"example": "你好&world"})
        _, _, kwargs = session.calls[1]
        self.assertEqual(kwargs["multipart"].parts,
                         [{"name": "example", "data": "你好&world".encode()}])
        self.assertTrue(kwargs["multipart"].closed)
        self.assertNotIn("data", kwargs)
        self.assertNotIn("files", kwargs)

    async def test_multipart_cleanup_on_uncertain_write(self):
        class FakeMime:
            instances = []
            def __init__(self):
                self.closed = False
                self.instances.append(self)
            def addpart(self, **kwargs):
                pass
            def close(self):
                self.closed = True
        fake_cffi = ModuleType("curl_cffi")
        fake_cffi.CurlMime = FakeMime
        fake_cffi.__path__ = []
        t, session = self.transport([Reply(version="v1")], allow_writes=True)
        await t.get_json("/profile/ajax/overview")
        session.error = RuntimeError("synthetic network failure")
        sample = b"%PDF-1.4\n%%EOF\n"
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi}):
            with self.assertRaises(VerificationError):
                await t.request("POST", "/profile/ajax/resumeByBlock/portfolio",
                                multipart_fields={},
                                multipart_upload=BrowserUpload(
                                    "attachment", "synthetic.pdf",
                                    "application/pdf", sample))
        # The allocated form is closed without retry or raw credential leakage.
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(FakeMime.instances[0].closed)


if __name__ == "__main__":
    unittest.main()
