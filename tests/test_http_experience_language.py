"""Synthetic HTTP parity for 104 EXPERIENCE and LANGUAGE CRUD."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_experience_records import Client as ExperienceClient, ROW
from test_language_records import Client as LanguageClient, LOCAL

TOKEN = "synthetic-test-token-for-experience-language-0001"
EXPERIENCES = "/v1/tw104/resumes/synthetic/experiences"
LANGUAGES = "/v1/tw104/resumes/synthetic/languages/local"


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True
        )
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test.local"
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def headers(self, key="unique-synthetic-idempotency-0001", match="100"):
        return {
            "Authorization": f"Bearer {TOKEN}",
            "If-Match": match, "Idempotency-Key": key,
        }

    async def test_experience_update_delete_replay(self):
        fake = ExperienceClient()
        self.app.state.client = fake
        body = {"jobName": "Researcher"}
        first = await self.http.put(EXPERIENCES + "/1", json=body, headers=self.headers())
        repeat = await self.http.put(EXPERIENCES + "/1", json=body, headers=self.headers())
        conflict = await self.http.put(
            EXPERIENCES + "/1", json={"jobName": "Other"}, headers=self.headers()
        )
        self.assertEqual((first.status_code, repeat.status_code, conflict.status_code), (200, 200, 409))
        self.assertEqual(len(fake.transport.calls), 1)
        deleted = await self.http.delete(
            EXPERIENCES + "/1", headers=self.headers(
                key="experience-delete-synthetic-001",
                match=str(fake.doc["resumeTimestamp"])
            )
        )
        self.assertEqual(deleted.status_code, 200)

    async def test_experience_create_rejects_missing_and_stale(self):
        fake = ExperienceClient()
        self.app.state.client = fake
        complete = {k: deepcopy(v) for k, v in ROW.items() if k not in ("logo", "sort")}
        complete["companyName"] = "New Synthetic Co."
        bad = await self.http.post(
            EXPERIENCES, json={"companyName": "Incomplete"},
            headers=self.headers(key="exp-invalid-000000000001"),
        )
        stale = await self.http.post(
            EXPERIENCES, json=complete, headers=self.headers(
                key="exp-stale-000000000001", match="99"
            ),
        )
        self.assertEqual((bad.status_code, stale.status_code), (422, 412))
        self.assertEqual(fake.transport.calls, [])
        created = await self.http.post(
            EXPERIENCES, json=complete,
            headers=self.headers(key="exp-create-000000000001")
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["position"], 2)

    async def test_language_kind_validation_create_and_delete(self):
        fake = LanguageClient()
        self.app.state.client = fake
        bad_kind = await self.http.post(
            "/v1/tw104/resumes/synthetic/languages/invalid",
            json={"type": LOCAL["type"], "level": LOCAL["level"]},
            headers=self.headers()
        )
        self.assertEqual(bad_kind.status_code, 422)
        updated = await self.http.put(
            LANGUAGES + "/1", json={"level": {"text": "Excellent", "value": 5}},
            headers=self.headers(),
        )
        self.assertEqual(updated.status_code, 200)
        again = await self.http.put(
            LANGUAGES + "/1", json={"level": {"text": "Excellent", "value": 5}},
            headers=self.headers(),
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(fake.transport.calls), 1)
        deleted = await self.http.delete(
            LANGUAGES + "/1", headers=self.headers(
                key="language-delete-0000000001",
                match=str(fake.doc["resumeTimestamp"])
            )
        )
        self.assertEqual(deleted.status_code, 200)

    async def test_language_stale_invalid_and_ambiguous(self):
        fake = LanguageClient(ambiguous=True)
        self.app.state.client = fake
        headers = self.headers(key="language-ambiguous-000001")
        stale = await self.http.delete(
            LANGUAGES + "/1", headers=self.headers(match="99")
        )
        invalid = await self.http.put(
            LANGUAGES + "/1", json={"certificate": [{"id": 1}]},
            headers=self.headers(key="language-invalid-0000001")
        )
        first = await self.http.delete(LANGUAGES + "/1", headers=headers)
        repeat = await self.http.delete(LANGUAGES + "/1", headers=headers)
        self.assertEqual(
            (stale.status_code, invalid.status_code, first.status_code, repeat.status_code),
            (412, 422, 409, 409),
        )
        self.assertEqual(len(fake.transport.calls), 1)

    async def test_auth_headers_and_default_off(self):
        self.app.state.client = ExperienceClient()
        unauth = await self.http.delete(EXPERIENCES + "/1")
        no_match = await self.http.delete(
            EXPERIENCES + "/1", headers={"Authorization": "Bearer " + TOKEN}
        )
        self.assertEqual((unauth.status_code, no_match.status_code), (401, 428))
        off = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=False
        )
        off.state.client = ExperienceClient()
        off.state.action_lock = asyncio.Lock()
        off.state.idempotency_results = {}
        async with AsyncClient(
            transport=ASGITransport(app=off), base_url="http://test.local"
        ) as http:
            response = await http.delete(
                EXPERIENCES + "/1", headers=self.headers()
            )
            self.assertEqual(response.status_code, 501)


if __name__ == "__main__":
    unittest.main()
