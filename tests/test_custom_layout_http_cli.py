"""CLASSIC/BANNER localhost API/CLI parity, entirely synthetic."""
import argparse
import asyncio
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from job_platforms.cli import _parser, _run
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_custom_layout_records import Client, CONTENT

TOKEN = "synthetic-custom-layout-api-authorization-token-001"
ROOT = "/v1/tw104/resumes/synthetic/custom-layout"


def headers(version, key):
    return {"Authorization": "Bearer " + TOKEN,
            "If-Match": str(version), "Idempotency-Key": key}


class Browser:
    page = object()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False


class LayoutAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(AuthConfig("unused", "unused"), api_token=TOKEN,
                              allow_experimental_writes=True)
        self.client = Client()
        self.app.state.client = self.client
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(transport=ASGITransport(app=self.app),
                                base_url="http://localhost")
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    async def test_custom_themes_read_only_http_requires_bearer(self):
        denied = await self.http.get("/v1/tw104/custom-themes")
        allowed = await self.http.get(
            "/v1/tw104/custom-themes", headers={"Authorization": "Bearer " + TOKEN}
        )
        self.assertEqual((denied.status_code, allowed.status_code), (401, 200))
        self.assertEqual(
            [x["frontend_content_slots"] for x in allowed.json()["themes"]],
            [1, 1, 1, 2, 2],
        )
        self.assertFalse(allowed.json()["current_site_availability_verified"])
        self.assertEqual(self.client.transport.calls, [])
        self.assertEqual(self.client.doc, self.client.doc)

    async def test_create_update_delete_replay_and_different_payload_conflict(self):
        body = {"slot": 1, "theme": 2, "name": "Synthetic layout",
                "content": deepcopy(CONTENT)}
        noauth = await self.http.post(ROOT, json=body)
        made = await self.http.post(ROOT, json=body,
                                    headers=headers(100, "synthetic-layout-create-001"))
        replay = await self.http.post(ROOT, json=body,
                                      headers=headers(100, "synthetic-layout-create-001"))
        conflict = await self.http.post(ROOT, json={**body, "theme": 1},
                                        headers=headers(100, "synthetic-layout-create-001"))
        changed = await self.http.put(ROOT + "/1", json={"name": "Changed"},
                                      headers=headers(101, "synthetic-layout-update-001"))
        deleted = await self.http.delete(ROOT + "/1",
                                         headers=headers(102, "synthetic-layout-delete-001"))
        self.assertEqual([x.status_code for x in (
            noauth, made, replay, conflict, changed, deleted,
        )], [401, 200, 200, 409, 200, 200])
        self.assertEqual(made.json()["theme"], "BANNER")
        self.assertNotIn("custom1", self.client.doc)
        self.assertEqual([v[0] for v in self.client.transport.calls],
                         ["POST", "PUT", "DELETE"])

    async def test_bad_fields_media_stale_and_invalid_theme_do_not_write(self):
        body = {"slot": 1, "theme": 1, "name": "Synthetic",
                "content": deepcopy(CONTENT)}
        invalid = (
            ({**body, "theme": 5}, 422),
            ({**body, "content": {**CONTENT, "media": {"type": 1}}}, 422),
            ({**body, "content": {**CONTENT, "url": "javascript:alert(1)"}}, 422),
            ({**body, "unexpected": 1}, 422),
            ({**body, "slot": True}, 422),
        )
        for index, (data, status) in enumerate(invalid):
            response = await self.http.post(ROOT, json=data,
                headers=headers(100, f"synthetic-layout-invalid-{index}-0001"))
            self.assertEqual(response.status_code, status)
            self.assertEqual(self.app.state.idempotency_results, {})
        stale = await self.http.post(ROOT, json=body,
                                    headers=headers(99, "synthetic-layout-stale-0001"))
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(self.app.state.idempotency_results, {})
        self.assertEqual(self.client.transport.calls, [])

    async def test_uncertain_result_never_replays_post(self):
        self.client = Client(lost=True)
        self.app.state.client = self.client
        body = {"slot": 1, "theme": 1, "name": "Synthetic",
                "content": deepcopy(CONTENT)}
        key = "synthetic-layout-ambiguous-0001"
        first = await self.http.post(ROOT, json=body, headers=headers(100, key))
        replay = await self.http.post(ROOT, json=body, headers=headers(100, key))
        self.assertEqual((first.status_code, replay.status_code), (409, 409))
        self.assertEqual([v[0] for v in self.client.transport.calls], ["POST"])

    async def test_invalid_update_and_delete_do_not_reserve_idempotency(self):
        invalid_update = await self.http.put(
            ROOT + "/1", json={"theme": 2},
            headers=headers(100, "synthetic-layout-invalid-update-0001"),
        )
        invalid_delete = await self.http.delete(
            ROOT + "/1", headers=headers(100, "synthetic-layout-no-target-0001"),
        )
        self.assertEqual((invalid_update.status_code, invalid_delete.status_code),
                         (422, 422))
        self.assertEqual(self.app.state.idempotency_results, {})
        self.assertEqual(self.client.transport.calls, [])

    async def test_explicit_write_opt_in_required(self):
        app = create_app(AuthConfig("unused", "unused"), api_token=TOKEN,
                         allow_experimental_writes=False)
        app.state.client = Client()
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://localhost") as http:
            response = await http.post(ROOT, json={"slot": 1, "theme": 1,
                "name": "Synthetic", "content": CONTENT},
                headers=headers(100, "synthetic-layout-optin-0001"))
        self.assertEqual(response.status_code, 501)
        self.assertEqual(app.state.client.transport.calls, [])


class LayoutCLITests(unittest.IsolatedAsyncioTestCase):
    async def test_custom_themes_offline_without_credentials(self):
        with patch("job_platforms.cli.AuthConfig.from_env",
                   side_effect=AssertionError("Offline lookup must not read credentials")), \
             patch("job_platforms.cli.FreshBrowserSession",
                   side_effect=AssertionError("Offline lookup must not login")):
            with redirect_stdout(io.StringIO()) as output:
                await _run(_parser().parse_args(["custom-themes"]))
        data = json.loads(output.getvalue())
        self.assertTrue(data["read_only"])
        self.assertFalse(data["persisted"])
        self.assertEqual([theme["value"] for theme in data["themes"]], [1, 2, 3, 4, 5])

    async def test_cli_create_update_delete_and_no_invalid_option(self):
        client = Client()
        class Factory:
            SECTIONS = Client.SECTIONS
            def __new__(cls, _page):
                return client
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "synthetic-content.json"
            file.write_text(json.dumps(CONTENT), encoding="utf-8")
            with patch("job_platforms.cli.AuthConfig.from_env",
                       return_value=argparse.Namespace(headless=False)), \
                 patch("job_platforms.cli.FreshBrowserSession", return_value=Browser()), \
                 patch("job_platforms.cli.Resume104Client", Factory):
                async def cli(*args):
                    with redirect_stdout(io.StringIO()) as output:
                        await _run(_parser().parse_args(["custom-layout", *args]))
                    return json.loads(output.getvalue())
                common = ("synthetic", "--slot", "1", "--confirm",
                          "experimental-custom-layout-write")
                made = await cli("synthetic", "create", "--slot", "1", "--theme", "1",
                                 "--name", "Synthetic layout", "--content-file", str(file),
                                 "--if-match", "100", "--confirm",
                                 "experimental-custom-layout-write")
                self.assertEqual(made["theme"], "CLASSIC")
                changed = await cli("synthetic", "update", "--slot", "1",
                                    "--name", "New title", "--if-match", "101",
                                    "--confirm", "experimental-custom-layout-write")
                self.assertTrue(changed["verified"])
                removed = await cli("synthetic", "delete", "--slot", "1",
                                    "--if-match", "102", "--confirm",
                                    "experimental-custom-layout-write")
                self.assertTrue(removed["verified"])
            self.assertEqual([x[0] for x in client.transport.calls],
                             ["POST", "PUT", "DELETE"])
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                _parser().parse_args(["custom-layout", "synthetic", "create",
                    "--slot", "1", "--theme", "5", "--if-match", "100",
                    "--confirm", "experimental-custom-layout-write"])


if __name__ == "__main__":
    unittest.main()
