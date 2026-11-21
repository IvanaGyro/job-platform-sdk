"""Private SQLite HTTP idempotency survives application restarts, offline."""
from copy import deepcopy
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient

from job_platforms.http_api import create_app
from job_platforms.http_idempotency import (
    DuplicateReservationError, SQLiteIdempotencyJournal,
)
from job_platforms.providers.tw104.auth import AuthConfig
from test_skill_records import Client as SkillClient

TOKEN = "synthetic-bearer-token-for-durable-http-000000000000"
DATA = {"birthdayDocument": "synthetic-not-real-identity-token-123",
        "idType": 0, "selfIdentityConfirmed": False}
PATH = "/v1/tw104/resumes/synthetic/under18"

class Client:
    def __init__(self, fail=False):
        self.calls = []
        self.created = 0
        self.fail = fail
        self.doc = {"resume": {"vno": "synthetic"}, "resumeTimestamp": 123,
                    "under18": {"formData": {}}}

    async def create_resume(self):
        self.created += 1
        if self.fail:
            from job_platforms.core.errors import VerificationError
            raise VerificationError("Synthetic remote result unknown")
        return {"versionNo": "synthetic-created"}

    async def get_resume(self, version):
        assert version == "synthetic"
        return deepcopy(self.doc)

    async def mutate_under18(self, resume_id, action, *, changes,
                             expected_timestamp, acknowledge_identity_write):
        assert (resume_id, action, expected_timestamp, acknowledge_identity_write) == (
            "synthetic", "create", "123", True,
        )
        self.calls.append(deepcopy(changes))
        if self.fail:
            from job_platforms.core.errors import VerificationError
            raise VerificationError("Synthetic uncertain identity write")
        self.doc["under18"]["formData"] = {"under18": deepcopy(changes)}
        self.doc["resumeTimestamp"] += 1
        return {"resume_id": "synthetic", "section": "under18",
                "verified": True, "contains_identity_values": False}

class Browser:
    page = object()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return None

@unittest.skipIf(os.name == "nt", "POSIX private-file journal")
class JournalTests(unittest.TestCase):
    def test_pending_to_success_and_cross_process_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "operations.sqlite3"
            a = SQLiteIdempotencyJournal(path)
            key = ("SKILL", "synthetic", "synthetic-idempotency-key-0001")
            initial = {"state": "indeterminate", "fingerprint": "a" * 64}
            a[key] = initial
            b = SQLiteIdempotencyJournal(path)
            self.assertEqual(b[key], initial)
            with self.assertRaises(DuplicateReservationError):
                b[key] = initial
            a[key].update({"state": "succeeded", "result": {"verified": True}})
            self.assertEqual(b[key]["result"], {"verified": True})
            with self.assertRaises(ValueError):
                b[key].update({"state": "indeterminate"})
            a.close(); b.close()
            self.assertFalse(path.stat().st_mode & 0o077)
            self.assertNotIn(key[-1].encode(), path.read_bytes())

    def test_reject_insecure_disk_path_and_invalid_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "operations.sqlite3"
            path.write_bytes(b"fake")
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                SQLiteIdempotencyJournal(path)
            path.unlink()
            actual = Path(folder) / "real.sqlite3"
            with SQLiteIdempotencyJournal(actual) as store:
                with self.assertRaises(ValueError):
                    store[("TEST",)] = {"state": "succeeded"}
                for invalid in ([], ("",), ("OK", 1), "test"):
                    with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                        store.get(invalid)
            path.symlink_to(actual)
            with self.assertRaises(PermissionError):
                SQLiteIdempotencyJournal(path)
            with self.assertRaises(ValueError):
                SQLiteIdempotencyJournal("relative.sqlite3")
            with self.assertRaises(ValueError):
                SQLiteIdempotencyJournal(Path(folder) / "missing" / "db")

@unittest.skipIf(os.name == "nt", "POSIX private-file journal")
class DurableHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def launch(self, path: Path, upstream: Client):
        app = create_app(AuthConfig("unused", "unused"), api_token=TOKEN,
                         allow_experimental_writes=True,
                         idempotency_db_path=str(path))
        with patch("job_platforms.http_api.FreshBrowserSession", return_value=Browser()), \
             patch("job_platforms.http_api.Resume104Client", return_value=upstream):
            life = app.router.lifespan_context(app)
            await life.__aenter__()
        http = AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test.invalid")
        await http.__aenter__()
        return app, http, life

    async def shut_down(self, http, life):
        await http.__aexit__(None, None, None)
        await life.__aexit__(None, None, None)

    @staticmethod
    def headers(key: str, version="123") -> dict:
        return {"Authorization": "Bearer " + TOKEN,
                "Idempotency-Key": key, "If-Match": version,
                "X-Identity-Write-Acknowledgement": "true"}

    async def test_create_resume_success_survives_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "ops.db"
            first = Client()
            app, http, life = await self.launch(location, first)
            headers = {"Authorization": "Bearer " + TOKEN,
                       "Idempotency-Key": "synthetic-create-restart-00001"}
            result = await http.post("/v1/tw104/resumes", headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(first.created, 1)
            await self.shut_down(http, life)
            next_client = Client()
            app2, http2, life2 = await self.launch(location, next_client)
            replay = await http2.post("/v1/tw104/resumes", headers=headers)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json(), result.json())
            self.assertEqual(next_client.created, 0)
            await self.shut_down(http2, life2)

    async def test_sensitive_write_replays_without_persisting_identity_values(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "ops.db"
            first = Client()
            app, http, life = await self.launch(location, first)
            headers = self.headers("synthetic-under18-restart-0001")
            result = await http.post(PATH, json=DATA, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(first.calls), 1)
            await self.shut_down(http, life)
            self.assertNotIn(DATA["birthdayDocument"].encode(), location.read_bytes())
            self.assertNotIn(headers["Idempotency-Key"].encode(), location.read_bytes())
            next_client = Client()
            app2, http2, life2 = await self.launch(location, next_client)
            replay = await http2.post(PATH, json=DATA, headers=headers)
            changed = await http2.post(PATH, json={**DATA, "idType": 2}, headers=headers)
            self.assertEqual((replay.status_code, changed.status_code), (200, 409))
            self.assertEqual(replay.json(), result.json())
            self.assertEqual(next_client.calls, [])
            await self.shut_down(http2, life2)

    async def test_skill_update_is_replayed_without_second_native_put(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "ops.db"
            original = SkillClient()
            app, http, life = await self.launch(location, original)
            headers = self.headers("synthetic-skill-update-restart-0001")
            result = await http.put(
                "/v1/tw104/resumes/synthetic/skills/1",
                json={"desc": "Synthetic changed once"}, headers=headers,
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(original.transport.calls), 1)
            await self.shut_down(http, life)
            restored = SkillClient()
            app2, http2, life2 = await self.launch(location, restored)
            replay = await http2.put(
                "/v1/tw104/resumes/synthetic/skills/1",
                json={"desc": "Synthetic changed once"}, headers=headers,
            )
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json(), result.json())
            self.assertEqual(restored.transport.calls, [])
            await self.shut_down(http2, life2)

    async def test_insecure_journal_aborts_before_browser_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "bad.db"
            location.write_bytes(b"not-private")
            location.chmod(0o644)
            app = create_app(AuthConfig("unused", "unused"), api_token=TOKEN,
                             idempotency_db_path=str(location))
            with patch("job_platforms.http_api.FreshBrowserSession",
                       side_effect=AssertionError("Browser must not open")) as browser:
                with self.assertRaises(PermissionError):
                    async with app.router.lifespan_context(app):
                        pass
                browser.assert_not_called()

    async def test_failed_disk_success_record_leaves_key_pending_and_blocks_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "ops.db"
            live = Client()
            app, http, life = await self.launch(location, live)
            headers = self.headers("synthetic-journal-commit-failure-0001")
            journal = app.state.idempotency_results
            with patch.object(journal, "_update_existing",
                              side_effect=sqlite3.OperationalError("synthetic disk failure")):
                with self.assertRaises(sqlite3.OperationalError):
                    await http.post(PATH, json=DATA, headers=headers)
            self.assertEqual(len(live.calls), 1)
            self.assertEqual(journal[("UNDER18", "synthetic",
                headers["Idempotency-Key"])]["state"], "indeterminate")
            await self.shut_down(http, life)
            after_restart = Client()
            app2, http2, life2 = await self.launch(location, after_restart)
            replay = await http2.post(PATH, json=DATA, headers=headers)
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(after_restart.calls, [])
            await self.shut_down(http2, life2)

    async def test_uncertain_result_persists_and_blocks_retry_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "ops.db"
            failed = Client(fail=True)
            app, http, life = await self.launch(location, failed)
            headers = self.headers("synthetic-under18-pending-restart-0001")
            first = await http.post(PATH, json=DATA, headers=headers)
            self.assertEqual(first.status_code, 409)
            self.assertEqual(len(failed.calls), 1)
            await self.shut_down(http, life)
            next_client = Client()
            app2, http2, life2 = await self.launch(location, next_client)
            replay = await http2.post(PATH, json=DATA, headers=headers)
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(next_client.calls, [])
            await self.shut_down(http2, life2)


if __name__ == "__main__":
    unittest.main()
