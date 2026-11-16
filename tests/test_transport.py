"""Browser transport and resume client mocked tests; zero website requests."""
import unittest

from job_platforms.core.errors import AuthenticationRequired, ResumeNotFound
from job_platforms.providers.tw104.transport import BrowserTransport
from job_platforms.providers.tw104.client import Resume104Client


class FakePage:
    url = "https://pda.104.com.tw/profile/"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def evaluate(self, script, argument):
        self.calls.append(argument)
        return next(self.responses)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_read_uses_same_origin_endpoint(self):
        page = FakePage([{
            "status": 200,
            "content_type": "application/json",
            "data": {"data": {
                "resume": {"vno": "synthetic-1"},
                "bio": {"formData": {"bio": {"chi": "synthetic"}}},
            }},
        }])
        item = await Resume104Client(page).get_resume("synthetic-1")
        self.assertEqual(item["resume"]["vno"], "synthetic-1")
        self.assertEqual(page.calls[0]["path"],
                         "/profile/ajax/resumeByBlock?vno=synthetic-1")

    async def test_reject_cross_origin_paths(self):
        page = FakePage([])
        with self.assertRaises(ValueError):
            await BrowserTransport(page).get_json("https://example.invalid/")
        with self.assertRaises(ValueError):
            await BrowserTransport(page).get_json("//example.invalid/")
        self.assertFalse(page.calls)

    async def test_login_expiration(self):
        page = FakePage([{
            "status": 403, "content_type": "text/html", "data": None
        }])
        with self.assertRaises(AuthenticationRequired):
            await BrowserTransport(page).get_json("/profile/ajax/overview")

    async def test_list_resumes(self):
        page = FakePage([{
            "status": 200, "content_type": "application/json",
            "data": {"data": {"formData": {
                "overview": [{"versionNo": "synthetic-1"}]
            }}},
        }])
        items = await Resume104Client(page).list_resumes()
        self.assertEqual(len(items), 1)

    async def test_unknown_resume_version(self):
        page = FakePage([{
            "status": 200, "content_type": "application/json",
            "data": {"data": {"resume": {"vno": "another-version"}}},
        }])
        with self.assertRaises(ResumeNotFound):
            await Resume104Client(page).get_resume("synthetic-1")

    async def test_local_patch_plan_preserves_original(self):
        document = {"data": {
            "resume": {"vno": "synthetic-1"},
            "resumeTimestamp": 123,
            "bio": {"formData": {"bio": {"chi": "old"}}},
        }}
        page = FakePage([{
            "status": 200, "content_type": "application/json",
            "data": document,
        }])
        plan, preview = await Resume104Client(page).plan_edit(
            "synthetic-1", [
                {"op": "replace", "path": "/bio/formData/bio/chi",
                 "value": "new"}
            ]
        )
        self.assertEqual(plan.base_timestamp, 123)
        self.assertEqual(preview["bio"]["formData"]["bio"]["chi"], "new")
        self.assertEqual(document["data"]["bio"]["formData"]["bio"]["chi"],
                         "old")
