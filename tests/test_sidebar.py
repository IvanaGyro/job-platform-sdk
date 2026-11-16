"""Synthetic SIDEBAR integration tests. No personal resume information."""
import asyncio
import copy
import unittest

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.writers import (
    sidebar_data, section_request_body, validate_section_edit,
    checked_write_paths,
)


BASE = {
    "resume": {"vno": "synthetic"},
    "resumeTimestamp": 100,
    "sidebar": [
        {"id": "education", "completed": True, "customMeta": "keep"},
        {"id": "experience", "completed": False},
        {"id": "skill", "completed": True},
    ],
}


class Transport:
    def __init__(self, client):
        self.client = client
        self.calls = []

    async def put_json(self, path, data, *, params):
        self.calls.append((path, copy.deepcopy(data), params))
        assert path == "/profile/ajax/resumeByBlock/sidebar"
        ids = [item["id"] for item in data["blockValueList"]["sidebar"]]
        before = self.client.doc["sidebar"]
        self.client.doc["sidebar"] = [
            next(item for item in before if item["id"] == identifier)
            for identifier in ids
        ]
        self.client.doc["resumeTimestamp"] += 1
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self):
        self.doc = copy.deepcopy(BASE)
        self._write_lock = asyncio.Lock()
        self.transport = Transport(self)

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return copy.deepcopy(self.doc)


class SidebarTests(unittest.IsolatedAsyncioTestCase):
    def plan(self, records):
        return EditPlan("synthetic", 100, [
            JsonPatchOperation("replace", "/sidebar", records)
        ])

    async def test_reorder_and_readback_preserve_records(self):
        client = Client()
        expected = list(reversed(BASE["sidebar"]))
        outcome = await client.save_edit(self.plan(expected))
        self.assertEqual(outcome["verified_sections"], ["sidebar"])
        self.assertTrue(outcome["verified"])
        self.assertEqual(outcome["atomic"], False)
        self.assertEqual(client.doc["sidebar"], expected)
        self.assertEqual(client.doc["sidebar"][-1]["customMeta"], "keep")
        self.assertEqual(client.transport.calls, [
            ("/profile/ajax/resumeByBlock/sidebar",
             {"blockValueList": {"sidebar": [{"id": "skill"}, {"id": "experience"}, {"id": "education"}]}},
             {"vno": "synthetic"}),
        ])

    async def test_read_and_plan_support_native_array(self):
        client = Client()
        section = await client.get_section("synthetic", "sidebar")
        self.assertEqual(section, BASE["sidebar"])
        schema = await client.get_schema("synthetic")
        self.assertEqual(schema["sidebar"]["type"], "array")
        plan, desired = await client.plan_edit("synthetic", [
            {"op": "replace", "path": "/sidebar", "value": list(reversed(BASE["sidebar"]))}
        ])
        self.assertEqual(plan.base_timestamp, 100)
        self.assertEqual(desired["sidebar"][0]["id"], "skill")

    async def test_reject_add_remove_or_metadata_edits(self):
        for target in (
            BASE["sidebar"][:-1],
            BASE["sidebar"] + [{"id": "extra", "completed": False}],
            [{**BASE["sidebar"][0], "completed": False}, *BASE["sidebar"][1:]],
        ):
            with self.subTest(target_kind=len(target)):
                client = Client()
                with self.assertRaises(UnsupportedWrite):
                    await client.save_edit(self.plan(target))
                self.assertEqual(client.transport.calls, [])

    async def test_noop_does_not_send_put(self):
        client = Client()
        result = await client.save_edit(self.plan(BASE["sidebar"]))
        self.assertEqual(result["verified_sections"], [])
        self.assertFalse(result["persisted"])
        self.assertEqual(client.transport.calls, [])

    def test_reject_duplicate_ids_and_unsupported_nested_paths(self):
        bad = {"sidebar": [{"id": "education"}, {"id": "education"}]}
        with self.assertRaises(UnsupportedWrite):
            sidebar_data(bad)
        with self.assertRaises(UnsupportedWrite):
            checked_write_paths([JsonPatchOperation("replace", "/sidebar/0/id", "other")])

    def test_response_contract_is_source_mapped(self):
        self.assertEqual(
            section_request_body(BASE, "sidebar"),
            {"blockValueList": {"sidebar": [
                {"id": "education"}, {"id": "experience"}, {"id": "skill"}
            ]}},
        )


if __name__ == "__main__":
    unittest.main()
