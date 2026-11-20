"""104 batch CLI/HTTP orchestration, auth, restart, partial-write semantics."""
import argparse
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from job_platforms.cli import _parser, _run
from job_platforms.http_api import create_app
from job_platforms.http_idempotency import SQLiteIdempotencyJournal
from job_platforms.providers.tw104.auth import AuthConfig
from test_batch_edit import Fake, SKILL1, SKILL2, PATCH, THEME

TOKEN = "synthetic-batch-only-authorization-token-000001"
PATH = "/v1/tw104/resumes/synthetic/batch"


class BatchHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(AuthConfig("unused", "unused"),
                              api_token=TOKEN, allow_experimental_writes=True)
        self.fake = Fake()
        self.app.state.client = self.fake
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(transport=ASGITransport(app=self.app),
                                base_url="http://local.invalid")
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def headers(self, key="synthetic-batch-http-replay-00001", rev="100"):
        return {"Authorization": "Bearer " + TOKEN,
                "If-Match": rev, "Idempotency-Key": key}

    async def test_success_replay_and_conflicting_payload(self):
        steps = [SKILL1, PATCH, THEME]
        noauth = await self.http.post(PATH, json=steps)
        first = await self.http.post(PATH, json=steps, headers=self.headers())
        replay = await self.http.post(PATH, json=steps, headers=self.headers())
        collision = await self.http.post(PATH, json=[SKILL2], headers=self.headers())
        self.assertEqual(tuple(x.status_code for x in (
            noauth, first, replay, collision,
        )), (401, 200, 200, 409))
        self.assertEqual(first.json()["verified_steps"],
                         ["1:skill.update", "2:patch", "3:theme"])
        self.assertFalse(first.json()["atomic"])
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(self.fake.calls, ["skill.update", "plan", "patch", "theme"])
        self.assertNotIn(SKILL1["changes"]["desc"], first.text)

    async def test_bad_preflight_and_revision_do_not_reserve(self):
        invalid = await self.http.post(PATH, json=[SKILL1, {
            "type": "record", "section": "under18", "action": "delete",
        }], headers=self.headers("synthetic-batch-invalid-00001"))
        stale = await self.http.post(PATH, json=[SKILL1],
            headers=self.headers("synthetic-batch-stale-00001", "99"))
        missing = await self.http.post(PATH, json=[SKILL1],
            headers={"Authorization": "Bearer " + TOKEN})
        short = await self.http.post(PATH, json=[SKILL1],
            headers={"Authorization": "Bearer " + TOKEN, "If-Match": "100"})
        self.assertEqual(tuple(x.status_code for x in (
            invalid, stale, missing, short,
        )), (422, 412, 428, 400))
        self.assertEqual(self.app.state.idempotency_results, {})
        self.assertEqual(self.fake.calls, [])

    async def test_partial_write_reports_only_step_labels_and_replay_is_blocked(self):
        self.fake = Fake(fail_on="skill.delete")
        self.app.state.client = self.fake
        headers = self.headers("synthetic-batch-partial-00001")
        first = await self.http.post(PATH, json=[SKILL1, SKILL2], headers=headers)
        repeat = await self.http.post(PATH, json=[SKILL1, SKILL2], headers=headers)
        self.assertEqual((first.status_code, repeat.status_code), (409, 409))
        detail = first.json()["detail"]
        self.assertEqual(detail["verified_sections"], ["1:skill.update"])
        self.assertEqual(detail["failed_section"], "2:skill.delete")
        self.assertNotIn(SKILL1["changes"]["desc"], first.text)
        self.assertEqual(self.fake.calls, ["skill.update", "skill.delete"])

    async def test_disabled_endpoint(self):
        app = create_app(AuthConfig("unused", "unused"),
                         api_token=TOKEN, allow_experimental_writes=False)
        app.state.client = Fake()
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://local.invalid") as http:
            result = await http.post(PATH, json=[SKILL1], headers=self.headers())
        self.assertEqual(result.status_code, 501)
        self.assertEqual(app.state.client.calls, [])

class Browser:
    page = object()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False


class BatchCLITests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_private_file_dispatch_and_validated_confirmation(self):
        dummy = Fake()
        class ClientFactory:
            SECTIONS = ()
            def __new__(cls, _page):
                return dummy
            # the mock factory never performs any site operations
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "private-synthetic-batch.json"
            src.write_text(json.dumps([SKILL1, SKILL2]), encoding="utf-8")
            args = ["batch", "synthetic", "--steps-file", str(src),
                    "--if-match", "100", "--confirm", "experimental-nonatomic-batch"]
            with patch("job_platforms.cli.AuthConfig.from_env",
                       return_value=argparse.Namespace(headless=False)), \
                 patch("job_platforms.cli.FreshBrowserSession", return_value=Browser()), \
                 patch("job_platforms.cli.Resume104Client", ClientFactory):
                with redirect_stdout(io.StringIO()) as output:
                    await _run(_parser().parse_args(args))
            result = json.loads(output.getvalue())
            self.assertEqual(result["verified_steps"], ["1:skill.update", "2:skill.delete"])
            self.assertEqual(dummy.calls, ["skill.update", "skill.delete"])
            self.assertNotIn(SKILL1["changes"]["desc"], output.getvalue())
            with self.assertRaises(SystemExit):
                with redirect_stderr(io.StringIO()):
                    _parser().parse_args(args[:-1] + ["unknown-confirmation"])


class DurableBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_batch_result_survives_restart_without_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            location = Path(folder) / "batch.sqlite3"
            headers = {"Authorization": "Bearer " + TOKEN,
                       "If-Match": "100", "Idempotency-Key": "synthetic-batch-db-0001"}
            stored = None
            for turn in (1, 2):
                app = create_app(AuthConfig("unused", "unused"),
                                 api_token=TOKEN, allow_experimental_writes=True)
                client = Fake()
                app.state.client = client
                app.state.action_lock = asyncio.Lock()
                app.state.idempotency_results = SQLiteIdempotencyJournal(location)
                try:
                    async with AsyncClient(transport=ASGITransport(app=app),
                                           base_url="http://local.invalid") as http:
                        response = await http.post(PATH, json=[SKILL1, SKILL2],
                                                   headers=headers)
                    self.assertEqual(response.status_code, 200)
                    if turn == 1:
                        stored = response.json()
                        self.assertEqual(client.calls, ["skill.update", "skill.delete"])
                    else:
                        self.assertEqual(response.json(), stored)
                        self.assertEqual(client.calls, [])
                finally:
                    app.state.idempotency_results.close()
            self.assertNotIn(headers["Idempotency-Key"].encode(), location.read_bytes())
            self.assertNotIn(SKILL1["changes"]["desc"].encode(), location.read_bytes())


if __name__ == "__main__":
    unittest.main()
