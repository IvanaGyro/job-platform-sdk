"""Strict synthetic 104 SKILL record CRUD tests; no account access."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.skill_records import (
    skill_list, skill_operation_body, verify_skill_operation,
)

BASE = {
    "resume": {"vno": "synthetic"},
    "resumeTimestamp": 123,
    "skill": {
        "formData": {
            "themeChoose": {"selectedTheme": {"text": "Example", "value": 1}},
            "skills": [
                {"name": "Python", "desc": "First synthetic",
                 "tag": [{"text": "Automation", "value": "tag-a"}], "sort": 1},
                {"name": "C++", "desc": "Second synthetic", "tag": [], "sort": 2},
            ]
        }
    }
}


class FakeTransport:
    def __init__(self, client):
        self.client = client
        self.calls = []
        self.ambiguous = False

    async def request(self, method, path, *, params, json_data):
        self.calls.append((method, path, deepcopy(json_data), deepcopy(params)))
        assert path == "/profile/ajax/resumeByBlock/skill"
        assert params == {"vno": "synthetic"}
        data = json_data["blockValueList"]["skill"]
        records = self.client.doc["skill"]["formData"]["skills"]
        if method == "POST":
            record = data["skills"][0]
            records.append({**deepcopy(record), "sort": len(records) + 1})
        elif method == "PUT":
            record = data["skills"][0]
            records[record["sort"] - 1] = deepcopy(record)
        elif method == "DELETE":
            (position,) = data["skills"]["sort"]
            records.pop(position - 1)
            for index, record in enumerate(records, 1):
                record["sort"] = index
        else:
            raise AssertionError(method)
        self.client.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("synthetic response lost after commit")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, *, ambiguous=False):
        self.doc = deepcopy(BASE)
        self._write_lock = asyncio.Lock()
        self.transport = FakeTransport(self)
        self.transport.ambiguous = ambiguous

    async def get_resume(self, resume_id):
        if resume_id != "synthetic":
            raise AssertionError("unexpected resume ID")
        return deepcopy(self.doc)


class SkillRecordTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_appends_single_record(self):
        client = Client()
        result = await client.mutate_skill(
            "synthetic", "create", expected_timestamp=123,
            changes={"name": "Rust", "desc": "", "tag": []}
        )
        self.assertEqual(result["position"], 3)
        self.assertTrue(result["verified"])
        self.assertEqual(client.doc["skill"]["formData"]["skills"][:2],
                         BASE["skill"]["formData"]["skills"])
        method, path, body, _ = client.transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(body, {"blockValueList": {"skill": {
            "skills": [{"name": "Rust", "desc": "", "tag": []}],
            "themeChoose": {"selectedTheme": 1},
        }}})

    async def test_update_one_field_does_not_write_other_records(self):
        client = Client()
        result = await client.mutate_skill(
            "synthetic", "update", position=1, expected_timestamp=123,
            changes={"desc": "Updated synthetic"}
        )
        self.assertTrue(result["verified"])
        self.assertEqual(client.doc["skill"]["formData"]["skills"][1],
                         BASE["skill"]["formData"]["skills"][1])
        data = client.transport.calls[0][2]["blockValueList"]["skill"]["skills"]
        self.assertEqual(data[0]["name"], "Python")
        self.assertEqual(data[0]["desc"], "Updated synthetic")
        self.assertEqual(data[0]["sort"], 1)
        self.assertEqual(client.transport.calls[0][0], "PUT")

    async def test_delete_by_one_based_sort_index(self):
        client = Client()
        result = await client.mutate_skill(
            "synthetic", "delete", position=1, expected_timestamp=123
        )
        self.assertTrue(result["verified"])
        self.assertEqual(client.doc["skill"]["formData"]["skills"][0]["name"], "C++")
        self.assertEqual(client.doc["skill"]["formData"]["skills"][0]["sort"], 1)
        method, _, body, _ = client.transport.calls[0]
        self.assertEqual(method, "DELETE")
        self.assertEqual(body, {"blockValueList": {
            "skill": {"skills": {"sort": [1]}}
        }})

    async def test_stale_timestamp_aborts_without_request(self):
        client = Client()
        with self.assertRaises(ConflictError):
            await client.mutate_skill(
                "synthetic", "delete", position=1, expected_timestamp=122
            )
        self.assertEqual(client.transport.calls, [])

    async def test_reject_unsafe_inputs(self):
        for operation,changes,position in [
            ("create", {"desc": "no name"}, None),
            ("create", {"name": "", "tag": []}, None),
            ("create", {"name": "a", "tag": [{"value": "missing-text"}]}, None),
            ("create", {"name": "a", "unknownField": True}, None),
            ("update", {"sort": 55}, 1),
            ("update", {"name": ""}, 1),
            ("update", {"name": "test"}, 0),
            ("update", {"desc": 3}, 1),
            ("delete", {"name": "invalid"}, 1),
            ("delete", None, 100),
        ]:
            with self.subTest(operation=operation, changes=changes, position=position):
                client = Client()
                with self.assertRaises(UnsupportedWrite):
                    await client.mutate_skill(
                        "synthetic", operation,
                        changes=changes, position=position, expected_timestamp=123,
                    )
                self.assertEqual(client.transport.calls, [])

    async def test_ambiguous_response_is_not_automatically_retried(self):
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.mutate_skill(
                "synthetic", "create", expected_timestamp=123,
                changes={"name": "Synthetic new skill"},
            )
        self.assertEqual(len(client.transport.calls), 1)
        self.assertEqual(len(client.doc["skill"]["formData"]["skills"]), 3)

    async def test_malformed_existing_record_disables_writes(self):
        client = Client()
        client.doc["skill"]["formData"]["skills"][0]["tag"].append({"text": "missing value"})
        with self.assertRaises(UnsupportedWrite):
            await client.mutate_skill(
                "synthetic", "create", expected_timestamp=123,
                changes={"name": "Synthetic"}
            )
        self.assertEqual(client.transport.calls, [])

    def test_compares_unaffected_records_during_readback(self):
        before=deepcopy(BASE)
        body=skill_operation_body(
            before, "create", changes={"name": "new", "desc": "", "tag": []}
        )
        after=deepcopy(before)
        after["skill"]["formData"]["skills"].append(
            {"sort": 3, "name": "new", "desc": "", "tag": []}
        )
        after["skill"]["formData"]["skills"][0]["desc"]="Unexpected concurrent edit"
        self.assertFalse(verify_skill_operation(before, after, "create",body=body,position=None))


if __name__ == "__main__":
    unittest.main()
