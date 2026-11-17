"""HTTP 104 INFO PATCH: synthetic only, no actual browser or account."""
import asyncio
import unittest

from httpx import ASGITransport, AsyncClient
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_info_fields import Client

TOKEN = "synthetic-http-info-test-token-long-enough-001"
ROOT = "/v1/tw104/resumes/synthetic"
PATCH = [{"op": "replace", "path": "/info/formData/info/motto", "value": "Build more"}]


def headers(key="synthetic-http-info-idempotency-00001", match="100"):
    return {
        "Authorization": "Bearer " + TOKEN, "If-Match": match,
        "Idempotency-Key": key,
    }


class InfoHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        app.state.client = Client()
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        self.app = app
        self.http = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.local",
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    async def test_plan_then_patch_with_replay_and_conflict(self):
        plan = await self.http.post(
            ROOT + "/plan", headers={"Authorization": "Bearer " + TOKEN},
            json=PATCH,
        )
        self.assertEqual(plan.status_code, 200)
        self.assertFalse(plan.json()["persisted"])
        first = await self.http.patch(ROOT, json=PATCH, headers=headers())
        replay = await self.http.patch(ROOT, json=PATCH, headers=headers())
        mismatch = await self.http.patch(
            ROOT, json=[{**PATCH[0], "value": "different"}], headers=headers()
        )
        self.assertEqual(
            (first.status_code, replay.status_code, mismatch.status_code),
            (200, 200, 409),
        )
        self.assertEqual(len(self.app.state.client.transport.calls), 1)
        self.assertEqual(first.json()["verified_sections"], ["info"])

    async def test_unmapped_account_field_never_write(self):
        request = [{
            "op": "replace", "path": "/info/formData/info/cellphone",
            "value": "0123456789",
        }]
        rejected = await self.http.patch(
            ROOT, json=request, headers=headers(key="synthetic-info-invalid-00001")
        )
        self.assertEqual(rejected.status_code, 501)
        self.assertEqual(self.app.state.client.transport.calls, [])

    async def test_disabled_default_and_stale_precondition(self):
        stale = await self.http.patch(ROOT, json=PATCH, headers=headers(match="99"))
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(self.app.state.client.transport.calls, [])
        off = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=False,
        )
        off.state.client = Client()
        off.state.action_lock = asyncio.Lock()
        off.state.idempotency_results = {}
        async with AsyncClient(
            transport=ASGITransport(app=off), base_url="http://test.local"
        ) as http:
            disabled = await http.patch(ROOT, json=PATCH, headers=headers())
            self.assertEqual(disabled.status_code, 501)


if __name__ == "__main__":
    unittest.main()
