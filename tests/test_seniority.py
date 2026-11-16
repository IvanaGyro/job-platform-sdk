"""Synthetic verification for 104 seniority-only experience writer."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.writers import (
    experience_seniority_data, section_request_body, checked_write_paths,
)

BASE = {
    "resume": {"vno": "synthetic"},
    "resumeTimestamp": 123,
    "experience": {
        "formData": {
            "seniority": {"text": "Before", "value": 1},
            "experiences": [
                {"companyName": "Synthetic company", "description": "Do not touch"}
            ],
        }
    },
}


class Transport:
    def __init__(self, client):
        self.client = client
        self.calls = []
    async def put_json(self, path, data, *, params):
        self.calls.append((path, deepcopy(data), params))
        assert path == "/profile/ajax/resumeByBlock/experience"
        obj = data["blockValueList"]["experience"]
        assert set(obj) == {"seniority"}, "Never resend experiences in a seniority PUT"
        record = self.client.doc["experience"]["formData"]["seniority"]
        record["value"] = obj["seniority"]
        record["text"] = "Server-normalized synthetic display text"
        self.client.doc["resumeTimestamp"] += 1
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self):
        self.doc = deepcopy(BASE)
        self._write_lock = asyncio.Lock()
        self.transport = Transport(self)
    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class SeniorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_only_seniority_and_preserves_experiences(self):
        client = Client()
        old_records = deepcopy(client.doc["experience"]["formData"]["experiences"])
        plan = EditPlan("synthetic", 123, [
            JsonPatchOperation("replace", "/experience/formData/seniority/value", 3)
        ])
        result = await client.save_edit(plan)
        self.assertEqual(result["verified_sections"], ["experience"])
        self.assertTrue(result["verified"])
        self.assertEqual(client.transport.calls, [
            ("/profile/ajax/resumeByBlock/experience",
             {"blockValueList": {"experience": {"seniority": 3}}},
             {"vno": "synthetic"})
        ])
        self.assertEqual(
            client.doc["experience"]["formData"]["experiences"], old_records
        )

    def test_rejects_full_experience_changes(self):
        with self.assertRaises(UnsupportedWrite):
            checked_write_paths([
                JsonPatchOperation(
                    "replace", "/experience/formData/experiences/0/description",
                    "Not yet supported"
                )
            ])

    def test_empty_original_can_be_replaced_but_not_submitted_as_empty(self):
        doc = deepcopy(BASE)
        doc["experience"]["formData"]["seniority"]["value"] = None
        self.assertEqual(experience_seniority_data(doc), {"value": None})
        with self.assertRaises(UnsupportedWrite):
            section_request_body(doc, "experience")
        doc["experience"]["formData"]["seniority"]["value"] = 2
        self.assertEqual(
            section_request_body(doc, "experience"),
            {"blockValueList": {"experience": {"seniority": 2}}}
        )

    async def test_rejects_invalid_target_before_network_write(self):
        client = Client()
        plan = EditPlan("synthetic", 123, [
            JsonPatchOperation("replace", "/experience/formData/seniority/value", [])
        ])
        with self.assertRaises(UnsupportedWrite):
            await client.save_edit(plan)
        self.assertEqual(client.transport.calls, [])


if __name__ == "__main__":
    unittest.main()
