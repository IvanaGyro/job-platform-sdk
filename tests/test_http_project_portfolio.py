"""HTTP end-to-end synthetic safety tests for PROJECT and PORTFOLIO routes."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient

from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_project_records import (
    Client as ProjectClient, CHANGES as PROJECT_CHANGES,
    POPULATED as PROJECT_POPULATED,
)
from test_portfolio_records import (
    Client as PortfolioClient, POPULATED as PORTFOLIO_POPULATED,
    LINK as PORTFOLIO_LINK,
)

TOKEN = "synthetic-project-portfolio-api-token-001"
P = "/v1/tw104/resumes/synthetic"


class HttpProjectPortfolioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        self.project = ProjectClient()
        self.app.state.client = self.project
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test.invalid"
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def headers(self, timestamp="100", key="project-portfolio-key000001"):
        return {
            "Authorization": "Bearer " + TOKEN,
            "If-Match": timestamp,
            "Idempotency-Key": key,
        }

    async def test_project_first_post_replay_conflict_and_update_delete(self):
        headers = self.headers(key="project-create-key-000001")
        first = await self.http.post(
            P + "/projects", json=PROJECT_CHANGES, headers=headers
        )
        replay = await self.http.post(
            P + "/projects", json=PROJECT_CHANGES, headers=headers
        )
        conflicting = await self.http.post(
            P + "/projects",
            json={**PROJECT_CHANGES, "name": "Another Synthetic"},
            headers=headers,
        )
        self.assertEqual(
            (first.status_code, replay.status_code, conflicting.status_code),
            (200, 200, 409),
        )
        self.assertEqual(len(self.project.transport.calls), 1)

        updated = await self.http.put(
            P + "/projects/1", json={"name": "Updated Synthetic"},
            headers=self.headers("101", "project-update-key-000001"),
        )
        self.assertEqual(updated.status_code, 200)
        deleted = await self.http.delete(
            P + "/projects/1",
            headers=self.headers("102", "project-delete-key-000001"),
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            [x[0] for x in self.project.transport.calls],
            ["POST", "PUT", "DELETE"],
        )

    async def test_reject_project_media_and_stale_without_remote_call(self):
        invalid = await self.http.post(
            P + "/projects",
            json={**PROJECT_CHANGES, "img": {"type": 1}},
            headers=self.headers(key="project-media-unsafe-key-0001"),
        )
        stale = await self.http.post(
            P + "/projects",
            json=PROJECT_CHANGES,
            headers=self.headers(timestamp="99", key="project-stale-key-00001"),
        )
        missing = await self.http.post(P + "/projects", json=PROJECT_CHANGES)
        self.assertEqual(
            (invalid.status_code, stale.status_code, missing.status_code),
            (422, 412, 401),
        )
        self.assertEqual(len(self.project.transport.calls), 0)

    async def test_portfolio_delete_replay_and_version_validation(self):
        self.app.state.client = PortfolioClient()
        headers = self.headers(key="portfolio-delete-key-00001")
        first = await self.http.delete(
            P + "/portfolios/2", headers=headers
        )
        replay = await self.http.delete(
            P + "/portfolios/2", headers=headers
        )
        conflict = await self.http.delete(
            P + "/portfolios/1", headers=headers
        )
        self.assertEqual(
            (first.status_code, replay.status_code, conflict.status_code),
            (200, 200, 409),
        )
        self.assertEqual(len(self.app.state.client.transport.calls), 1)

    async def test_portfolio_link_post_with_multipart_replay_and_collision(self):
        self.app.state.client = PortfolioClient()
        headers = self.headers(key="portfolio-link-create-key-000001")
        first = await self.http.post(
            P + "/portfolios", json=PORTFOLIO_LINK, headers=headers,
        )
        replay = await self.http.post(
            P + "/portfolios", json=PORTFOLIO_LINK, headers=headers,
        )
        mismatch = await self.http.post(
            P + "/portfolios",
            json={**PORTFOLIO_LINK, "name": "Another"},
            headers=headers,
        )
        self.assertEqual(
            (first.status_code, replay.status_code, mismatch.status_code),
            (200, 200, 409),
        )
        self.assertEqual(
            self.app.state.client.transport.calls[0][0], "POST",
        )
        self.assertEqual(len(self.app.state.client.transport.calls), 1)

    async def test_portfolio_link_invalid_payload_does_not_mutate(self):
        self.app.state.client = PortfolioClient()
        invalid = await self.http.post(
            P + "/portfolios",
            json={**PORTFOLIO_LINK, "url": "file:///etc/passwd"},
            headers=self.headers(key="portfolio-link-invalid-key-00001"),
        )
        stale = await self.http.post(
            P + "/portfolios", json=PORTFOLIO_LINK,
            headers=self.headers("99", "portfolio-link-stale-key-00001"),
        )
        self.assertEqual((invalid.status_code, stale.status_code), (422, 412))
        self.assertEqual(self.app.state.client.transport.calls, [])

    async def test_portfolio_delete_bad_index_is_422(self):
        self.app.state.client = PortfolioClient()
        invalid = await self.http.delete(
            P + "/portfolios/42", headers=self.headers()
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertFalse(self.app.state.client.transport.calls)

    async def test_native_project_and_portfolio_sort(self):
        for section, fake in (
            ("project", ProjectClient(doc=PROJECT_POPULATED)),
            ("portfolio", PortfolioClient(doc=PORTFOLIO_POPULATED)),
        ):
            with self.subTest(section=section):
                self.app.state.idempotency_results = {}
                self.app.state.client = fake
                headers = self.headers(key="sort-" + section + "-key-00001")
                payload = {"from": 1, "to": 2}
                path = P + "/sort/" + section
                first = await self.http.put(path, json=payload, headers=headers)
                replay = await self.http.put(path, json=payload, headers=headers)
                self.assertEqual((first.status_code, replay.status_code), (200, 200))
                self.assertEqual(len(fake.transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
