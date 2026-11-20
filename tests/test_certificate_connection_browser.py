"""P0-07 official frontend Vuex certificate link operations, synthetic only."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient
from job_platforms.core.errors import (
    ConflictError, UnsupportedWrite, VerificationError,
)
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.certificate_connection_records import (
    linked_certificate_ids, verify_certificate_association,
)
from job_platforms.providers.tw104.transport import BrowserTransport

TOKEN = "synthetic-certification-bearer-000000000001"
BASE = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "bio": {"formData": {"bio": {"chi": "Unchanged", "eng": ""}}},
    "certificate": {"formData": {
        "themeChoose": {"selectedTheme": {"value": 1, "text": "Theme"}},
        "certificate": {"certifications": [], "certificates": [], "others": "Synthetic"},
    }},
}


def groups(ids):
    return ([{"category": 7, "items": [{"id": n, "name": "Synthetic"} for n in ids]}]
            if ids else [])


class Page:
    def __init__(self, owner, fail=False, collateral=False):
        self.owner = owner
        self.calls = []
        self.fail = fail
        self.collateral = collateral

    async def evaluate(self, script, values):
        self.calls.append(deepcopy(values))
        assert "form/certificate/setCertificationConnect" in script
        assert "form/certificate/deleteCertificationConnect" in script
        assert "form/certificate/getCertificationList" in script
        assert values["vno"] == "synthetic"
        if self.fail:
            raise RuntimeError("Simulated remote ambiguous response: must not log private values")
        currently = set(linked_certificate_ids(self.owner.doc))
        if values["action"] == "connect":
            ids = values["ids"]
            assert set(ids) <= {11, 22}
            new_ids = ids
        else:
            assert values["recordId"] in currently
            new_ids = sorted(currently - {values["recordId"]})
        self.owner.doc["certificate"]["formData"]["certificate"]["certifications"] = groups(new_ids)
        self.owner.doc["resumeTimestamp"] += 1
        if self.collateral:
            self.owner.doc["bio"]["formData"]["bio"]["chi"] = "Corrupted"
        return {"submitted": True}


class Client(Resume104Client):
    def __init__(self, *, doc=BASE, fail=False, collateral=False):
        self.doc = deepcopy(doc)
        self.page = Page(self, fail=fail, collateral=collateral)
        self.transport = BrowserTransport(self.page)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class P007BrowserTests(unittest.IsolatedAsyncioTestCase):
    def test_grouped_native_get_id_shape(self):
        doc = deepcopy(BASE)
        doc["certificate"]["formData"]["certificate"]["certifications"] = groups([11, 22])
        self.assertEqual(linked_certificate_ids(doc), {11, 22})
        for bad in (
            [{"category": 1, "items": [{"id": True}]}],
            [{"category": 1, "items": [{"id": 11}, {"id": 11}]}],
            [{"category": 1, "items": ["11"]}],
            [{"category": 1}],
            [{"category": None, "items": []}],
        ):
            with self.subTest(bad=bad), self.assertRaises(UnsupportedWrite):
                doc["certificate"]["formData"]["certificate"]["certifications"] = bad
                linked_certificate_ids(doc)

    def test_linked_state_verifier_preserves_existing_other_fields(self):
        before = deepcopy(BASE)
        after = deepcopy(BASE)
        after["certificate"]["formData"]["certificate"]["certifications"] = groups([11])
        self.assertTrue(verify_certificate_association(
            before, after, desired_ids=frozenset({11}),
        ))
        after["certificate"]["formData"]["certificate"]["certificates"] = [
            {"name": "Unexpected other certificate"}
        ]
        self.assertFalse(verify_certificate_association(
            before, after, desired_ids=frozenset({11}),
        ))
        after["certificate"]["formData"]["certificate"]["certificates"] = []
        after["certificate"]["formData"]["certificate"]["others"] = "Overwritten"
        self.assertFalse(verify_certificate_association(
            before, after, desired_ids=frozenset({11}),
        ))

    async def test_official_frontend_connect_then_disconnect_and_restore(self):
        client = Client()
        expected = 100
        for action, ids, record_id, target in (
            ("connect", [11], None, {11}),
            ("connect", [11, 22], None, {11, 22}),
            ("disconnect", None, 22, {11}),
            ("disconnect", None, 11, set()),
        ):
            with self.subTest(action=action, target=target):
                result = await client.mutate_certificate_connections(
                    "synthetic", action, ids=ids, record_id=record_id,
                    expected_timestamp=expected,
                )
                self.assertTrue(result["verified"])
                self.assertEqual(result["source"], "official_browser_vuex")
                self.assertEqual(result["linked_count"], len(target))
                self.assertEqual(linked_certificate_ids(client.doc), target)
                self.assertNotIn("11", str(result))
                expected += 1
        self.assertEqual(client.doc["certificate"], BASE["certificate"])
        self.assertEqual(client.doc["bio"], BASE["bio"])
        self.assertEqual(len(client.page.calls), 4)

    async def test_prewrite_strict_validation_and_stale_guard(self):
        for action, fields, issue in (
            ("connect", {"ids": []}, UnsupportedWrite),
            ("connect", {"ids": [11, 11]}, UnsupportedWrite),
            ("connect", {"ids": [True]}, UnsupportedWrite),
            ("connect", {"ids": list(range(1, 22))}, UnsupportedWrite),
            ("connect", {"ids": [11], "record_id": 11}, UnsupportedWrite),
            ("disconnect", {"record_id": 11}, UnsupportedWrite),
            ("disconnect", {"ids": [11], "record_id": 11}, UnsupportedWrite),
            ("clear_all", {}, UnsupportedWrite),
        ):
            client = Client()
            with self.subTest(action=action, fields=fields):
                with self.assertRaises(issue):
                    await client.mutate_certificate_connections(
                        "synthetic", action, expected_timestamp=100, **fields,
                    )
                self.assertEqual(client.page.calls, [])
        client = Client()
        with self.assertRaises(ConflictError):
            await client.mutate_certificate_connections(
                "synthetic", "connect", ids=[11], expected_timestamp=101,
            )
        self.assertEqual(client.page.calls, [])

    async def test_ambiguous_browser_action_never_retried(self):
        client = Client(fail=True)
        with self.assertRaises(VerificationError) as error:
            await client.mutate_certificate_connections(
                "synthetic", "connect", ids=[11], expected_timestamp=100,
            )
        self.assertNotIn("private values", str(error.exception))
        self.assertEqual(len(client.page.calls), 1)

    async def test_collateral_resume_mutation_is_not_verified(self):
        client = Client(collateral=True)
        with self.assertRaises(VerificationError):
            await client.mutate_certificate_connections(
                "synthetic", "connect", ids=[11], expected_timestamp=100,
            )
        self.assertEqual(len(client.page.calls), 1)

class P007HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        self.client = Client()
        self.app.state.client = self.client
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://local.invalid",
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def headers(self, key="synthetic-cert-association-0001", revision="100"):
        return {
            "Authorization": "Bearer " + TOKEN,
            "If-Match": revision,
            "Idempotency-Key": key,
        }

    async def test_http_connect_disconnect_and_idempotency(self):
        url = "/v1/tw104/resumes/synthetic/certificate-links"
        unauth = await self.http.put(url, json={"ids": [11]})
        first = await self.http.put(url, json={"ids": [11]}, headers=self.headers())
        replay = await self.http.put(url, json={"ids": [11]}, headers=self.headers())
        collision = await self.http.put(url, json={"ids": [22]}, headers=self.headers())
        delete = await self.http.delete(url + "/11", headers=self.headers(
            "synthetic-cert-disconnect-0001", "101",
        ))
        self.assertEqual(
            (unauth.status_code, first.status_code, replay.status_code,
             collision.status_code, delete.status_code),
            (401, 200, 200, 409, 200),
        )
        self.assertEqual(first.json()["linked_count"], 1)
        self.assertEqual(len(self.client.page.calls), 2)
        self.assertEqual(self.client.doc["certificate"], BASE["certificate"])

    async def test_preflight_invalid_and_stale_do_not_reserve(self):
        url = "/v1/tw104/resumes/synthetic/certificate-links"
        missing = await self.http.put(url, json={"ids": [11]}, headers={
            "Authorization": "Bearer " + TOKEN,
        })
        invalid = await self.http.put(url, json={"ids": [True]},
                                      headers=self.headers("synthetic-cert-invalid-0001"))
        stale = await self.http.put(url, json={"ids": [11]},
                                    headers=self.headers("synthetic-cert-stale-00001", "99"))
        self.assertEqual((missing.status_code, invalid.status_code, stale.status_code),
                         (428, 422, 412))
        self.assertEqual(self.client.page.calls, [])
        self.assertEqual(self.app.state.idempotency_results, {})

    async def test_ambiguous_result_replay_blocked(self):
        self.client = Client(fail=True)
        self.app.state.client = self.client
        url = "/v1/tw104/resumes/synthetic/certificate-links"
        headers = self.headers("synthetic-cert-indeterminate-0001")
        first = await self.http.put(url, json={"ids": [11]}, headers=headers)
        second = await self.http.put(url, json={"ids": [11]}, headers=headers)
        self.assertEqual((first.status_code, second.status_code), (409, 409))
        self.assertEqual(len(self.client.page.calls), 1)

    async def test_disabled_writer_uses_no_site_calls(self):
        app = create_app(AuthConfig("unused", "unused"), api_token=TOKEN,
                         allow_experimental_writes=False)
        app.state.client = Client()
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://local.invalid") as http:
            result = await http.put(
                "/v1/tw104/resumes/synthetic/certificate-links",
                json={"ids": [11]}, headers=self.headers(),
            )
        self.assertEqual(result.status_code, 501)
        self.assertEqual(app.state.client.page.calls, [])


class P007CLITests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_dispatch_and_unknown_confirmation(self):
        import argparse
        from contextlib import redirect_stdout, redirect_stderr
        import io
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from job_platforms.cli import _parser, _run

        class Browser:
            page = object()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                return False

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "synthetic-private-cert-ids.json"
            source.write_text(json.dumps([11]), encoding="utf-8")
            client = Client()
            argv = [
                "certificate-links", "synthetic", "connect",
                "--ids-file", str(source), "--if-match", "100",
                "--confirm", "experimental-certificate-association-write",
            ]
            with patch("job_platforms.cli.AuthConfig.from_env",
                       return_value=argparse.Namespace(headless=False)), \
                 patch("job_platforms.cli.FreshBrowserSession", return_value=Browser()), \
                 patch("job_platforms.cli.Resume104Client", return_value=client):
                with redirect_stdout(io.StringIO()) as out:
                    await _run(_parser().parse_args(argv))
            result = json.loads(out.getvalue())
            self.assertTrue(result["verified"])
            self.assertEqual(client.page.calls[0]["action"], "connect")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                _parser().parse_args(argv[:-1] + ["unknown-confirmation"])
