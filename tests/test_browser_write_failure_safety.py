"""BrowserTransport failure classification and no blind resubmission."""
import unittest
from job_platforms.core.errors import (
    AuthenticationRequired, ConflictError, VerificationError, UpstreamError,
)
from job_platforms.providers.tw104.transport import BrowserTransport

class FakePage:
    url = "https://pda.104.com.tw/profile"
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
    async def evaluate(self, script, args):
        self.calls.append(args)
        return next(self.replies)

class WriteFailureTests(unittest.IsolatedAsyncioTestCase):
    def new(self, reply):
        page = FakePage([reply])
        transport = BrowserTransport(page)
        transport._profile_version = "synthetic-v1"
        return transport, page

    async def test_version_conflicts_are_not_silent(self):
        for status in (409, 412):
            with self.subTest(status=status):
                transport, page = self.new({
                    "status":status, "content_type":"application/json",
                    "data":{"data":{}}, "profile_version":None,
                })
                with self.assertRaises(ConflictError):
                    await transport.put_json("/profile/ajax/resumeByBlock/bio", {})
                self.assertEqual(len(page.calls), 1)

    async def test_write_response_must_not_be_classified_as_read_error(self):
        for status, data in (
            (401,None), (403,None), (500,None), (200,None),
        ):
            with self.subTest(status=status):
                transport, page = self.new({
                    "status": status, "content_type":"text/html",
                    "data":data, "profile_version":None,
                })
                with self.assertRaises(VerificationError):
                    await transport.put_json("/profile/ajax/resumeByBlock/bio", {})
                self.assertEqual(len(page.calls),1)

    async def test_patch_is_revision_guarded(self):
        page = FakePage([{"status":200,"content_type":"application/json",
                          "data":{"data":{}},"profile_version":"v2"}])
        transport = BrowserTransport(page)
        with self.assertRaises(VerificationError):
            await transport.request("PATCH","/profile/ajax/resumeByBlock/bio",
                                    json_data={})
        self.assertFalse(page.calls)
        transport._profile_version = "v1"
        await transport.request("PATCH","/profile/ajax/resumeByBlock/bio",
                                json_data={})
        self.assertEqual(page.calls[0]["profile_version"],"v1")
        self.assertEqual(transport._profile_version,"v2")

    async def test_get_auth_and_nonjson_still_distinguishable(self):
        for status, data, err in (
            (401,None,AuthenticationRequired),
            (403,None,AuthenticationRequired),
            (200,None,UpstreamError),
        ):
            with self.subTest(status=status):
                transport, _ = self.new({
                    "status":status,"content_type":"text/html",
                    "data":data,"profile_version":None,
                })
                with self.assertRaises(err):
                    await transport.get_json("/profile/ajax/overview")

if __name__ == "__main__":
    unittest.main()
