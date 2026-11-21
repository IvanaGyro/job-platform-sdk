"""104 LANGUAGE adjacent reorder: native local/foreign buckets and read-back."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.record_sort import sort_body, verify_sort
from test_language_records import BASE as SINGLE, FOREIGN, LOCAL

TOKEN = "synthetic-language-sort-token-00000001"
PATH = "/v1/tw104/resumes/synthetic/sort/language"


def two_languages():
    data = deepcopy(SINGLE)
    data["language"]["formData"]["languages"]["local"].append({
        **deepcopy(LOCAL), "sort": 2,
        "type": {"text": "Taiwanese", "value": 2},
    })
    data["language"]["formData"]["languages"]["foreign"].append({
        **deepcopy(FOREIGN), "sort": 2,
        "type": {"text": "French", "value": 3},
    })
    return data


class Transport:
    def __init__(self, client, *, ambiguous=False):
        self.owner = client
        self.calls = []
        self.ambiguous = ambiguous

    async def put_json(self, path, body, *, params):
        assert path == "/profile/ajax/swapRecordBySort/language"
        assert params == {"vno": "synthetic"}
        self.calls.append((path, deepcopy(body)))
        payload = body["blockValueList"]["language"]["languages"]
        kind = "foreign" if isinstance(payload["foreign"]["sort"], dict) else "local"
        inactive = "local" if kind == "foreign" else "foreign"
        assert payload[inactive] == {"sort": []}
        move = payload[kind]["sort"]
        rows = self.owner.doc["language"]["formData"]["languages"][kind]
        i, j = move["from"] - 1, move["to"] - 1
        rows[i], rows[j] = rows[j], rows[i]
        for n, row in enumerate(rows, start=1):
            row["sort"] = n
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Synthetic lost response")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, *, ambiguous=False):
        self.doc = two_languages()
        self.transport = Transport(self, ambiguous=ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, version):
        assert version == "synthetic"
        return deepcopy(self.doc)


class LanguageSortTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_language_sort_wire_contract(self):
        doc = two_languages()
        self.assertEqual(
            sort_body(doc, "language", 1, 2, kind="foreign"),
            {"blockValueList": {"language": {"languages": {
                "foreign": {"sort": {"from": 1, "to": 2}},
                "local": {"sort": []},
            }}}},
        )
        self.assertEqual(
            sort_body(doc, "language", 2, 1, kind="local"),
            {"blockValueList": {"language": {"languages": {
                "foreign": {"sort": []},
                "local": {"sort": {"from": 2, "to": 1}},
            }}}},
        )
        for section, kind in (
            ("language", None), ("skill", "foreign"), ("language", "other"),
        ):
            with self.subTest(section=section, kind=kind):
                with self.assertRaises(UnsupportedWrite):
                    sort_body(doc, section, 1, 2, kind=kind)
        with self.assertRaises(UnsupportedWrite):
            sort_body(doc, "language", 1, 1, kind="local")

    async def test_sort_one_language_branch_leaves_other_unchanged(self):
        client = Client()
        foreign = deepcopy(client.doc["language"]["formData"]["languages"]["foreign"])
        result = await client.sort_records(
            "synthetic", "language", 1, 2,
            kind="local", expected_timestamp=100
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["kind"], "local")
        self.assertEqual(
            client.doc["language"]["formData"]["languages"]["foreign"],
            foreign,
        )
        with self.assertRaises(ConflictError):
            await client.sort_records(
                "synthetic", "language", 2, 1,
                kind="local", expected_timestamp=100
            )
        self.assertEqual(len(client.transport.calls), 1)

    def test_concurrent_changes_rejected(self):
        old = two_languages()
        after = deepcopy(old)
        records = after["language"]["formData"]["languages"]["local"]
        records[0], records[1] = records[1], records[0]
        for i, row in enumerate(records, 1):
            row["sort"] = i
        self.assertTrue(verify_sort(
            old, after, "language", 1, 2, kind="local"
        ))
        after["language"]["formData"]["languages"]["foreign"][0]["speaking"]["value"] = 1
        self.assertFalse(verify_sort(
            old, after, "language", 1, 2, kind="local"
        ))

    async def test_no_retry_after_ambiguous_write(self):
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.sort_records(
                "synthetic", "language", 1, 2,
                kind="foreign", expected_timestamp=100,
            )
        self.assertEqual(len(client.transport.calls), 1)

    async def test_http_success_replay_and_validation(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        fake = Client()
        app.state.client = fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        headers = {
            "Authorization": "Bearer " + TOKEN,
            "If-Match": "100",
            "Idempotency-Key": "language-sort-idempotency-0001",
        }
        payload = {"kind": "local", "from": 1, "to": 2}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.invalid"
        ) as http:
            bad = await http.put(PATH, json={"from": 1, "to": 2}, headers=headers)
            self.assertEqual(bad.status_code, 422)
            valid = await http.put(PATH, json=payload, headers=headers)
            replay = await http.put(PATH, json=payload, headers=headers)
            diff = await http.put(
                PATH, json={**payload, "kind": "foreign"}, headers=headers
            )
        self.assertEqual(
            (valid.status_code, replay.status_code, diff.status_code),
            (200, 200, 409),
        )
        self.assertEqual(len(fake.transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
