"""HTTP If-Match never accepts nonexistent 104 revisions or reserves keys."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient

from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig

TOKEN = "synthetic-revision-token-for-http-tests-0001"
ROOT = "/v1/tw104/resumes/synthetic"


class NoWriteClient:
    def __init__(self, stamp):
        self.doc = {}
        if stamp is not MISSING:
            self.doc["resumeTimestamp"] = stamp
        self.writes = 0
        self.reads = 0

    async def get_resume(self, version):
        assert version == "synthetic"
        self.reads += 1
        return deepcopy(self.doc)

    async def plan_edit(self, version, operations):
        assert version == "synthetic"
        self.reads += 1
        return EditPlan("synthetic", self.doc.get("resumeTimestamp"), [
            JsonPatchOperation.from_dict(x) for x in operations
        ]), {}

    async def save_edit(self, plan):
        self.writes += 1
        raise AssertionError("No HTTP write permitted without a revision")


MISSING = object()


class RevisionApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://localhost",
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def headers(self, revision, suffix):
        return {
            "Authorization": f"Bearer {TOKEN}",
            "If-Match": revision,
            "Idempotency-Key": f"synthetic-revision-check-{suffix}-00001",
        }

    async def test_all_native_delete_routes_reject_missing_revision(self):
        paths = (
            "/skills/1", "/educations/1", "/experiences/1",
            "/referrers/1", "/projects/1", "/portfolios/1",
            "/languages/foreign/1", "/custom-text/1", "/certificate-block",
        )
        for stamp, expected in ((MISSING, "None"), (None, "None"),
                                 ("null", "null"), (False, "False")):
            for i, suffix in enumerate(paths):
                with self.subTest(stamp=repr(stamp), path=suffix):
                    mock = NoWriteClient(stamp)
                    self.app.state.client = mock
                    response = await self.http.delete(
                        ROOT + suffix,
                        headers=self.headers(expected, f"delete-{i}-{repr(stamp)}"),
                    )
                    self.assertEqual(response.status_code, 412)
                    self.assertEqual(mock.writes, 0)
                    self.assertEqual(self.app.state.idempotency_results, {})

    async def test_json_patch_rejects_unversioned_preflight_before_reservation(self):
        operations = [{
            "op": "replace", "path": "/bio/formData/bio/chi", "value": "Synthetic",
        }]
        for stamp, expected in ((MISSING, "None"), (None, "None"),
                                 ("undefined", "undefined"),
                                 (True, "True")):
            with self.subTest(stamp=repr(stamp)):
                mock = NoWriteClient(stamp)
                self.app.state.client = mock
                response = await self.http.patch(
                    ROOT, json=operations,
                    headers=self.headers(expected, f"patch-{repr(stamp)}"),
                )
                self.assertEqual(response.status_code, 412)
                self.assertEqual(mock.writes, 0)
                self.assertEqual(self.app.state.idempotency_results, {})


if __name__ == "__main__":
    unittest.main()
