"""104 REFERRER HTTP routes: synthetic, no real personal contact records."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient

from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_referrer_records import Client, EMPTY, POPULATED, FIRST

TOKEN = "synthetic-referrer-token-for-http-tests"
PATH = "/v1/tw104/resumes/synthetic/referrers"
NEW = {k: deepcopy(v) for k, v in FIRST.items() if k != "sort"}


class ReferrerHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        self.fake = Client()
        self.app.state.client = self.fake
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test.invalid",
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def headers(self, key="referrer-test-idempotency-key-0001", timestamp="100"):
        return {
            "Authorization": f"Bearer {TOKEN}",
            "If-Match": timestamp,
            "Idempotency-Key": key,
        }

    async def test_initial_create_replay_and_conflicting_idempotency(self):
        first = await self.http.post(PATH, json=NEW, headers=self.headers())
        repeat = await self.http.post(PATH, json=NEW, headers=self.headers())
        conflict = await self.http.post(
            PATH, json={**NEW, "name": "Other Synthetic"},
            headers=self.headers(),
        )
        self.assertEqual((first.status_code, repeat.status_code, conflict.status_code), (200, 200, 409))
        self.assertEqual(first.json()["position"], 1)
        self.assertEqual(len(self.fake.transport.calls), 1)

    async def test_update_and_delete(self):
        self.fake = Client(doc=POPULATED)
        self.app.state.client = self.fake
        change = await self.http.put(
            PATH + "/2", json={"position": "Engineer"},
            headers=self.headers(key="referrer-update-test-key-0001"),
        )
        self.assertEqual(change.status_code, 200)
        self.assertEqual(self.fake.transport.calls[0][0], "PUT")
        delete = await self.http.delete(
            PATH + "/1",
            headers=self.headers(
                key="referrer-delete-test-key-0001",
                timestamp=str(self.fake.doc["resumeTimestamp"]),
            ),
        )
        self.assertEqual(delete.status_code, 200)
        self.assertEqual(self.fake.transport.calls[1][0], "DELETE")

    async def test_bad_field_stale_and_unauthorized(self):
        wrong = await self.http.post(
            PATH, json={"name": "Incomplete"},
            headers=self.headers(key="referrer-invalid-request-key"),
        )
        stale = await self.http.post(
            PATH, json=NEW, headers=self.headers(
                key="referrer-stale-request-key", timestamp="99",
            ),
        )
        unauth = await self.http.post(PATH, json=NEW)
        no_match = await self.http.post(
            PATH, json=NEW, headers={"Authorization": f"Bearer {TOKEN}"},
        )
        self.assertEqual(
            (wrong.status_code, stale.status_code, unauth.status_code, no_match.status_code),
            (422, 412, 401, 428),
        )
        self.assertEqual(self.fake.transport.calls, [])

    async def test_ambiguous_remote_write_never_resubmitted(self):
        self.fake = Client(doc=POPULATED, ambiguous=True)
        self.app.state.client = self.fake
        headers = self.headers(key="referrer-uncertain-response-key")
        first = await self.http.delete(PATH + "/1", headers=headers)
        repeat = await self.http.delete(PATH + "/1", headers=headers)
        self.assertEqual((first.status_code, repeat.status_code), (409, 409))
        self.assertEqual(len(self.fake.transport.calls), 1)

    async def test_experimental_feature_flag_defaults_off(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=False,
        )
        fake = Client(doc=EMPTY)
        app.state.client = fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.invalid",
        ) as http:
            response = await http.post(PATH, json=NEW, headers=self.headers())
            self.assertEqual(response.status_code, 501)
        self.assertFalse(fake.transport.calls)


if __name__ == "__main__":
    unittest.main()
