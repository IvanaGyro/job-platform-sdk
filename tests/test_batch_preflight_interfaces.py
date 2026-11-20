"""Auth-only HTTP and one-session CLI 104 batch planning, read only."""
import argparse
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
from job_platforms.providers.tw104.auth import AuthConfig
from test_skill_records import Client as SkillClient
from test_batch_edit import SKILL1, SKILL2

TOKEN = "synthetic-plan-auth-bearer-00000000000001"
URL = "/v1/tw104/resumes/synthetic/batch/plan"


class PlanHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # The read-only plan must work when *all experimental writes are off*.
        self.app = create_app(AuthConfig("unused", "unused"),
                              api_token=TOKEN, allow_experimental_writes=False)
        self.client = SkillClient()
        self.app.state.client = self.client
        self.http = AsyncClient(transport=ASGITransport(app=self.app),
                                base_url="http://local.invalid")
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    async def test_auth_and_current_site_source_preflight_no_write(self):
        invalid_auth = await self.http.post(URL, json=[SKILL1])
        response = await self.http.post(URL, json=[SKILL1, SKILL2],
            headers={"Authorization": "Bearer " + TOKEN, "If-Match": "123"})
        self.assertEqual((invalid_auth.status_code, response.status_code), (401, 200))
        body = response.json()
        self.assertEqual(body["resumeTimestamp"], 123)
        self.assertEqual(body["steps"][0]["status"], "eligible_on_current_snapshot")
        self.assertEqual(body["steps"][1]["status"], "deferred_pending_prior_steps")
        self.assertFalse(body["persisted"])
        self.assertFalse(body["network_write_sent"])
        self.assertEqual(self.client.transport.calls, [])
        self.assertNotIn(SKILL1["changes"]["desc"], response.text)

    async def test_conflict_bad_step_and_missing_revision(self):
        headers = {"Authorization": "Bearer " + TOKEN, "If-Match": "123"}
        bad = await self.http.post(URL, json=[{**SKILL1, "section": "under18"}],
                                   headers=headers)
        conflict = await self.http.post(URL, json=[SKILL1], headers={
            **headers, "If-Match": "122"})
        missing = await self.http.post(URL, json=[SKILL1], headers={
            "Authorization": "Bearer " + TOKEN})
        self.assertEqual((bad.status_code, conflict.status_code,
                          missing.status_code), (422, 412, 428))
        self.assertEqual(self.client.transport.calls, [])

    async def test_first_step_invalid_record_does_not_pass_preflight(self):
        response = await self.http.post(URL, json=[{**SKILL1, "position": 101}],
            headers={"Authorization": "Bearer " + TOKEN, "If-Match": "123"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.transport.calls, [])


class Browser:
    page = object()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False


class PlanCLITests(unittest.IsolatedAsyncioTestCase):
    async def test_no_confirm_flag_or_write_on_cli_batch_plan(self):
        client = SkillClient()
        with tempfile.TemporaryDirectory() as folder:
            steps = Path(folder) / "private-synthetic-batch.json"
            steps.write_text(json.dumps([SKILL1, SKILL2]), encoding="utf-8")
            args = ["batch-plan", "synthetic", "--steps-file", str(steps),
                    "--if-match", "123"]
            with patch("job_platforms.cli.AuthConfig.from_env",
                       return_value=argparse.Namespace(headless=False)), \
                 patch("job_platforms.cli.FreshBrowserSession", return_value=Browser()), \
                 patch("job_platforms.cli.Resume104Client", return_value=client):
                with redirect_stdout(io.StringIO()) as output:
                    await _run(_parser().parse_args(args))
            result = json.loads(output.getvalue())
            self.assertEqual(result["steps"][0]["label"], "1:skill.update")
            self.assertFalse(result["network_write_sent"])
            self.assertEqual(client.transport.calls, [])
            self.assertNotIn(SKILL1["changes"]["desc"], output.getvalue())
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                _parser().parse_args(args + ["--confirm", "anything"])


if __name__ == "__main__":
    unittest.main()
