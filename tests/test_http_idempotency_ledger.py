"""Durable HTTP at-most-once reservations, without real resume data."""
import asyncio
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from job_platforms.http_api import create_app
from job_platforms.http_idempotency import DurableIdempotencyLedger
from job_platforms.providers.tw104.auth import AuthConfig
from test_referrer_records import Client, FIRST

TOKEN = "synthetic-durable-test-token-long-enough-0001"
PATH = "/v1/tw104/resumes/synthetic/referrers"
NEW = {k: v for k, v in FIRST.items() if k != "sort"}


class DurableLedgerTests(unittest.IsolatedAsyncioTestCase):
    def test_hash_only_file_and_permission_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / "mutations.sqlite3"
            ledger = DurableIdempotencyLedger(str(filename))
            try:
                self.assertEqual(filename.stat().st_mode & 0o777, 0o600)
                key = ("POST", "synthetic-private-id", "private-random-key")
                fingerprint = hashlib.sha256(b"synthetic private request").hexdigest()
                ledger[key] = {"state": "indeterminate", "fingerprint": fingerprint}
                self.assertIsNotNone(ledger.get(key))
                ledger.get(key).update({"state": "succeeded", "result": {
                    "private": "SHOULD_NOT_APPEAR_IN_SQLITE",
                }})
                self.assertEqual(ledger.get(key)["state"], "succeeded")
            finally:
                ledger.close()
            db = filename.read_bytes()
            for forbidden in (
                b"synthetic-private-id", b"private-random-key",
                b"SHOULD_NOT_APPEAR_IN_SQLITE", b"synthetic private request",
            ):
                self.assertNotIn(forbidden, db)
            resumed = DurableIdempotencyLedger(str(filename))
            try:
                old = resumed.get(key)
                self.assertEqual(old["state"], "indeterminate")
                self.assertNotIn("result", old)
                self.assertEqual(old["fingerprint"], fingerprint)
                with self.assertRaises(HTTPException) as caught:
                    resumed[key] = {"state": "indeterminate", "fingerprint": fingerprint}
                self.assertEqual(caught.exception.status_code, 409)
            finally:
                resumed.close()

    def test_cross_process_race_is_blocked_by_sqlite_primary_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "mutations.sqlite3")
            first = DurableIdempotencyLedger(path)
            second = DurableIdempotencyLedger(path)
            try:
                key = ("REFERRER", "synthetic", "same-key")
                record = {"state": "indeterminate", "fingerprint": "a" * 64}
                first[key] = record
                with self.assertRaises(HTTPException) as caught:
                    second[key] = record
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(second.get(key)["state"], "indeterminate")
            finally:
                first.close()
                second.close()

    def test_symlink_database_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            dst = Path(folder) / "real.sqlite3"
            dst.touch()
            shortcut = Path(folder) / "fake.sqlite3"
            shortcut.symlink_to(dst)
            with self.assertRaises(ValueError):
                DurableIdempotencyLedger(str(shortcut))

    async def test_lifespan_configures_optional_ledger(self):
        class FakeSession:
            page = object()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                return False

        with tempfile.TemporaryDirectory() as folder:
            filename = str(Path(folder) / "mutations.sqlite3")
            app = create_app(
                AuthConfig("unused", "unused"), api_token=TOKEN,
                idempotency_db_path=filename,
            )
            with patch("job_platforms.http_api.FreshBrowserSession",
                       return_value=FakeSession()):
                async with app.router.lifespan_context(app):
                    self.assertIsInstance(
                        app.state.idempotency_results,
                        DurableIdempotencyLedger,
                    )
                    self.assertTrue(Path(filename).exists())
                    ledger = app.state.idempotency_results
                    ledger[("synthetic", "key")] = {
                        "state": "indeterminate", "fingerprint": "d" * 64
                    }
            reopened = DurableIdempotencyLedger(filename)
            try:
                self.assertEqual(
                    reopened.get(("synthetic", "key"))["state"],
                    "indeterminate",
                )
            finally:
                reopened.close()

    async def test_http_replay_is_200_only_until_restart_then_409(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "mutations.sqlite3")
            ledger = DurableIdempotencyLedger(path)
            app = create_app(
                AuthConfig("unused", "unused"), api_token=TOKEN,
                allow_experimental_writes=True, idempotency_db_path=path,
            )
            fake = Client()
            app.state.client = fake
            app.state.action_lock = asyncio.Lock()
            app.state.idempotency_results = ledger
            headers = {
                "Authorization": f"Bearer {TOKEN}", "If-Match": "100",
                "Idempotency-Key": "synthetic-persistent-reference-key",
            }
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test.invalid",
                ) as http:
                    first = await http.post(PATH, json=NEW, headers=headers)
                    replay = await http.post(PATH, json=NEW, headers=headers)
                    self.assertEqual((first.status_code, replay.status_code), (200, 200))
                    self.assertEqual(len(fake.transport.calls), 1)
            finally:
                ledger.close()

            restarted = DurableIdempotencyLedger(path)
            app.state.idempotency_results = restarted
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test.invalid",
                ) as http:
                    after_restart = await http.post(PATH, json=NEW, headers=headers)
                    changed = await http.post(
                        PATH, json={**NEW, "position": "Other"},
                        headers=headers,
                    )
                    self.assertEqual((after_restart.status_code, changed.status_code), (409, 409))
                    self.assertEqual(len(fake.transport.calls), 1)
            finally:
                restarted.close()

    async def test_failed_remote_write_leaves_reservation_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = str(Path(folder) / "mutations.sqlite3")
            ledger = DurableIdempotencyLedger(filename)
            app = create_app(
                AuthConfig("unused", "unused"), api_token=TOKEN,
                allow_experimental_writes=True,
            )
            fake = Client(ambiguous=True)
            app.state.client = fake
            app.state.action_lock = asyncio.Lock()
            app.state.idempotency_results = ledger
            headers = {
                "Authorization": "Bearer " + TOKEN, "If-Match": "100",
                "Idempotency-Key": "synthetic-uncertain-reference-key",
            }
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test.invalid",
                ) as http:
                    uncertain = await http.post(PATH, json=NEW, headers=headers)
                    self.assertEqual(uncertain.status_code, 409)
            finally:
                ledger.close()

            after_restart = DurableIdempotencyLedger(filename)
            app.state.idempotency_results = after_restart
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test.invalid",
                ) as http:
                    another = await http.post(PATH, json=NEW, headers=headers)
                    self.assertEqual(another.status_code, 409)
                self.assertEqual(len(fake.transport.calls), 1)
            finally:
                after_restart.close()


if __name__ == "__main__":
    unittest.main()
