"""104 EDUCATION HTTP routes: synthetic test server, no external account."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_education_records import Client, ROW

TOKEN = "synthetic-test-token-for-education-0001"
PATH = "/v1/tw104/resumes/synthetic/educations"
NEW = {k: deepcopy(v) for k, v in ROW.items() if k != "sort"}
NEW["name"] = "New Synthetic School"


class EducationHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        self.fake = Client()
        app.state.client = self.fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        self.http = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.local"
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def headers(self, *, key="synthetic-education-key-0000001", match="100"):
        return {
            "Authorization": "Bearer " + TOKEN,
            "If-Match": match,
            "Idempotency-Key": key,
        }

    async def test_create_replay_and_conflicting_key(self):
        first = await self.http.post(PATH, headers=self.headers(), json=NEW)
        repeat = await self.http.post(PATH, headers=self.headers(), json=NEW)
        conflict = await self.http.post(
            PATH, headers=self.headers(), json={**NEW, "name": "Other"}
        )
        self.assertEqual(
            (first.status_code, repeat.status_code, conflict.status_code),
            (200, 200, 409),
        )
        self.assertEqual(first.json()["position"], 2)
        self.assertEqual(len(self.fake.transport.calls), 1)

    async def test_update_then_delete(self):
        put = await self.http.put(
            PATH + "/1", json={"name": "Renamed Synthetic School"},
            headers=self.headers(key="synthetic-education-put-key-0001"),
        )
        self.assertEqual(put.status_code, 200)
        self.assertEqual(self.fake.transport.calls[0][0], "PUT")
        delete = await self.http.delete(
            PATH + "/1",
            headers=self.headers(
                key="synthetic-education-delete-key-01",
                match=str(self.fake.doc["resumeTimestamp"]),
            ),
        )
        self.assertEqual(delete.status_code, 200)
        self.assertEqual(self.fake.transport.calls[1][0], "DELETE")

    async def test_requires_auth_and_safe_preconditions(self):
        unauth = await self.http.post(PATH, json=NEW)
        bare = {"Authorization": "Bearer " + TOKEN}
        missing_match = await self.http.post(PATH, json=NEW, headers=bare)
        missing_key = await self.http.post(
            PATH, json=NEW, headers={**bare, "If-Match": "100"}
        )
        self.assertEqual(
            (unauth.status_code, missing_match.status_code, missing_key.status_code),
            (401, 428, 400),
        )
        self.assertFalse(self.fake.transport.calls)

    async def test_stale_or_invalid_changes_are_rejected(self):
        stale = await self.http.post(
            PATH, json=NEW, headers=self.headers(match="99")
        )
        bad = await self.http.post(
            PATH, json={"name": "Only a name"},
            headers=self.headers(key="synthetic-education-bad-key-0001"),
        )
        missing = await self.http.put(
            PATH + "/99", json={"name": "Invalid position"},
            headers=self.headers(key="synthetic-education-index-key-01"),
        )
        self.assertEqual(
            (stale.status_code, bad.status_code, missing.status_code),
            (412, 422, 422),
        )
        self.assertFalse(self.fake.transport.calls)

    async def test_ambiguous_response_is_not_resubmitted(self):
        self.fake.transport.ambiguous = True
        headers = self.headers(key="synthetic-education-ambiguous-001")
        first = await self.http.post(PATH, json=NEW, headers=headers)
        repeat = await self.http.post(PATH, json=NEW, headers=headers)
        self.assertEqual((first.status_code, repeat.status_code), (409, 409))
        self.assertEqual(len(self.fake.transport.calls), 1)

    async def test_disabled_by_default(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=False,
        )
        app.state.client = self.fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.local"
        ) as client:
            response = await client.post(
                PATH, headers=self.headers(), json=NEW
            )
            self.assertEqual(response.status_code, 501)
            self.assertFalse(self.fake.transport.calls)


if __name__ == "__main__":
    unittest.main()
