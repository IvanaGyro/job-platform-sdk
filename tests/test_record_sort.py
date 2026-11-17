"""104 adjacent skill/education sort without live account mutations."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient
from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.record_sort import sort_body, verify_sort
from test_education_records import BASE as EDUCATION_BASE, ROW as EDUCATION_ROW

TOKEN = "synthetic-sort-test-token-long-enough-0001"
PATH = "/v1/tw104/resumes/synthetic/sort/education"

BASE = deepcopy(EDUCATION_BASE)
BASE["education"]["formData"]["educations"].append({
    **deepcopy(EDUCATION_ROW), "sort": 2, "name": "Synthetic College Two",
})


class Transport:
    def __init__(self, owner, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.ambiguous = ambiguous

    async def put_json(self, path, body, *, params):
        assert path == "/profile/ajax/swapRecordBySort/education"
        assert params == {"vno": "synthetic"}
        self.calls.append((path, deepcopy(body)))
        op = body["blockValueList"]["education"]["educations"]["sort"]
        rows = self.owner.doc["education"]["formData"]["educations"]
        i, j = op["from"] - 1, op["to"] - 1
        rows[i], rows[j] = rows[j], rows[i]
        for n, row in enumerate(rows, 1):
            row["sort"] = n
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Lost sort response")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, ambiguous=False):
        self.doc = deepcopy(BASE)
        self.transport = Transport(self, ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class SortTests(unittest.IsolatedAsyncioTestCase):
    def test_source_payload_adjacent_only(self):
        self.assertEqual(
            sort_body(BASE, "education", 2, 1),
            {"blockValueList": {"education": {
                "educations": {"sort": {"from": 2, "to": 1}},
            }}},
        )
        for section, start, end in (
            ("education", 0, 1), ("education", 1, 3),
            ("education", 1, 1), ("experience", 1, 2),
            ("education", True, 2),
        ):
            with self.subTest(section=section, start=start, end=end):
                with self.assertRaises(UnsupportedWrite):
                    sort_body(BASE, section, start, end)
        duplicate = deepcopy(BASE)
        duplicate["education"]["formData"]["educations"][1] = {
            **deepcopy(EDUCATION_ROW), "sort": 2
        }
        with self.assertRaises(UnsupportedWrite):
            sort_body(duplicate, "education", 1, 2)

    async def test_sort_readback_and_stale(self):
        client = Client()
        success = await client.sort_records(
            "synthetic", "education", 1, 2, expected_timestamp=100
        )
        self.assertTrue(success["verified"])
        self.assertEqual(len(client.transport.calls), 1)
        with self.assertRaises(ConflictError):
            await client.sort_records(
                "synthetic", "education", 1, 2, expected_timestamp=100
            )

    async def test_ambiguous_not_retried(self):
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.sort_records(
                "synthetic", "education", 1, 2, expected_timestamp=100
            )
        self.assertEqual(len(client.transport.calls), 1)

    def test_concurrent_sibling_mutation_fails(self):
        after = deepcopy(BASE)
        records = after["education"]["formData"]["educations"]
        records[0], records[1] = records[1], records[0]
        for i, row in enumerate(records, 1):
            row["sort"] = i
        self.assertTrue(verify_sort(BASE, after, "education", 1, 2))
        records[1]["name"] = "Unexpected"
        self.assertFalse(verify_sort(BASE, after, "education", 1, 2))

    async def test_http_replay_and_failures(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        fake = Client()
        app.state.client = fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        headers = {
            "Authorization": "Bearer " + TOKEN, "If-Match": "100",
            "Idempotency-Key": "synthetic-sort-key-0000000001",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test.local") as http:
            bad = await http.put(PATH, headers=headers, json={"from": 1, "to": 3})
            self.assertEqual(bad.status_code, 422)
            success = await http.put(PATH, headers=headers, json={"from": 1, "to": 2})
            replay = await http.put(PATH, headers=headers, json={"from": 1, "to": 2})
            conflict = await http.put(PATH, headers=headers, json={"from": 2, "to": 1})
            self.assertEqual(
                (success.status_code, replay.status_code, conflict.status_code),
                (200, 200, 409),
            )
            self.assertEqual(len(fake.transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
