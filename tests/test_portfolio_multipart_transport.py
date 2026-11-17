"""Same-origin browser multipart FormData construction, synthetic only."""
import unittest

from job_platforms.providers.tw104.transport import BrowserTransport


class FakePage:
    url = "https://pda.104.com.tw/profile"
    def __init__(self):
        self.args = []
    async def evaluate(self, script, args):
        assert "new FormData()" in script
        assert "body.append(key, value)" in script
        assert "headers['104-profile-ver'] = arg.profile_version" in script
        self.args.append(args)
        return {
            "status": 200, "content_type": "application/json",
            "data": {"data": {"portfolio": {"status": "SUCCESS"}}},
            "profile_version": "synthetic-version-next",
        }


class MultipartTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_multipart_link_uses_browser_header_and_form_entries(self):
        page = FakePage()
        transport = BrowserTransport(page)
        transport._profile_version = "synthetic-version-prev"
        response = await transport.request(
            "POST", "/profile/ajax/resumeByBlock/portfolio",
            params={"vno": "synthetic"},
            multipart_fields={
                "blockValueList[portfolio][attachType]": "2",
                "blockValueList[portfolio][attach][url]":
                    "https://example.invalid/link",
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(transport._profile_version, "synthetic-version-next")
        args = page.args[0]
        self.assertEqual(args["method"], "POST")
        self.assertEqual(args["json"], None)
        self.assertEqual(args["form"], None)
        self.assertIn("vno=synthetic", args["path"])
        self.assertEqual(
            args["multipart"]["blockValueList[portfolio][attachType]"], "2"
        )

    async def test_multipart_rejects_unsuitable_methods_and_mixed_bodies(self):
        page = FakePage()
        transport = BrowserTransport(page)
        transport._profile_version = "synthetic-version"
        for request in (
            {"method": "GET", "multipart_fields": {"k": "v"}},
            {"method": "POST", "multipart_fields": {}},
            {"method": "POST", "multipart_fields": {"k": 1}},
            {"method": "POST", "multipart_fields": {"k": "v"}, "json_data": {}},
            {"method": "POST", "multipart_fields": {"k": "v"}, "form_data": {}},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                await transport.request(
                    request.pop("method"), "/profile/ajax/resumeByBlock/portfolio",
                    **request,
                )
        self.assertFalse(page.args)

    async def test_profile_version_required_before_multipart_send(self):
        page = FakePage()
        transport = BrowserTransport(page)
        from job_platforms.core.errors import VerificationError
        with self.assertRaises(VerificationError):
            await transport.request(
                "POST", "/profile/ajax/resumeByBlock/portfolio",
                multipart_fields={"test": "test"},
            )
        self.assertFalse(page.args)


if __name__ == "__main__":
    unittest.main()
