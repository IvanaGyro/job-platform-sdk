"""Synthetic tests for certificate and non-atomic multi-section saves."""
import asyncio
import copy
import unittest

from job_platforms.core.errors import PartialWriteError, UnsupportedWrite
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.writers import (
    certificate_data, section_request_body, checked_write_paths,
)


BASE = {
    "resume": {"vno": "synthetic-id"},
    "resumeTimestamp": 123,
    "bio": {"formData": {"bio": {"chi": "hello", "eng": "hello"}}},
    "certificate": {
        "formData": {"certificate": {
            "certificates": [{"id": 7, "name": "Synthetic certificate"}],
            "others": "original",
            "certifications": [{"not_modified": True}],
        }}
    },
}


class FakeTransport:
    def __init__(self, client, fail_section=None):
        self.client = client
        self.fail_section = fail_section
        self.calls = []

    async def put_json(self, path, data, *, params):
        section = path.rsplit("/", 1)[-1]
        self.calls.append((path, copy.deepcopy(data), params))
        if section == self.fail_section:
            raise RuntimeError("synthetic failed response")
        new = data["blockValueList"][section]
        if section == "bio":
            self.client.doc["bio"]["formData"]["bio"] = copy.deepcopy(new["bio"])
        elif section == "certificate":
            self.client.doc["certificate"]["formData"]["certificate"].update(
                copy.deepcopy(new)
            )
        else:
            raise AssertionError("Unexpected synthetic block")
        self.client.doc["resumeTimestamp"] += 1
        return {"data": {}}


class WriterClient(Resume104Client):
    def __init__(self, fail_section=None):
        self.doc = copy.deepcopy(BASE)
        self.transport = FakeTransport(self, fail_section)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, version):
        assert str(version) == "synthetic-id"
        return copy.deepcopy(self.doc)


class MultiSectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_certificate_other_text_preserves_certificates(self):
        client = WriterClient()
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation(
                "replace", "/certificate/formData/certificate/others", "updated"
            )
        ])
        result = await client.save_edit(plan)
        self.assertTrue(result["verified"])
        self.assertEqual(result["verified_sections"], ["certificate"])
        self.assertFalse(result["atomic"])
        self.assertEqual(len(client.transport.calls), 1)
        path, data, params = client.transport.calls[0]
        self.assertEqual(path, "/profile/ajax/resumeByBlock/certificate")
        self.assertEqual(params, {"vno": "synthetic-id"})
        self.assertEqual(
            data["blockValueList"]["certificate"],
            {"certificates": [{"id": 7, "name": "Synthetic certificate"}],
             "others": "updated"},
        )
        self.assertEqual(
            client.doc["certificate"]["formData"]["certificate"]["certifications"],
            [{"not_modified": True}],
        )

    async def test_replacing_certificate_list(self):
        client = WriterClient()
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation(
                "replace", "/certificate/formData/certificate/certificates", []
            )
        ])
        result = await client.save_edit(plan)
        self.assertEqual(result["verified_sections"], ["certificate"])
        self.assertEqual(certificate_data(client.doc)["certificates"], [])

    async def test_multiple_sections_use_two_calls_and_are_not_atomic(self):
        client = WriterClient()
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation(
                "replace", "/bio/formData/bio/eng", "updated English"
            ),
            JsonPatchOperation(
                "replace", "/certificate/formData/certificate/others", "updated note"
            ),
        ])
        result = await client.save_edit(plan)
        self.assertEqual(result["verified_sections"], ["bio", "certificate"])
        self.assertEqual(
            [item[0] for item in client.transport.calls],
            [
                "/profile/ajax/resumeByBlock/bio",
                "/profile/ajax/resumeByBlock/certificate",
            ],
        )
        self.assertFalse(result["atomic"])
        self.assertTrue(result["persisted"])

    async def test_second_failure_reports_partial_completion(self):
        client = WriterClient(fail_section="certificate")
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation(
                "replace", "/bio/formData/bio/chi", "new Chinese"
            ),
            JsonPatchOperation(
                "replace", "/certificate/formData/certificate/others", "new other"
            ),
        ])
        with self.assertRaises(PartialWriteError) as ctx:
            await client.save_edit(plan)
        self.assertEqual(ctx.exception.verified_sections, ["bio"])
        self.assertEqual(ctx.exception.failed_section, "certificate")
        self.assertEqual(len(client.transport.calls), 2)
        self.assertEqual(client.doc["bio"]["formData"]["bio"]["chi"], "new Chinese")
        self.assertEqual(certificate_data(client.doc)["others"], "original")

    async def test_invalid_section_detected_before_any_put(self):
        client = WriterClient()
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation("replace", "/bio/formData/bio/eng", "new"),
            JsonPatchOperation(
                "replace", "/certificate/formData/certificate/others/0", "invalid"
            ),
        ])
        with self.assertRaises(UnsupportedWrite):
            await client.save_edit(plan)
        self.assertFalse(client.transport.calls)

    async def test_reject_invalid_certificate_list_before_write(self):
        client = WriterClient()
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation(
                "replace", "/certificate/formData/certificate/certificates", "invalid"
            )
        ])
        with self.assertRaises(UnsupportedWrite):
            await client.save_edit(plan)
        self.assertFalse(client.transport.calls)


if __name__ == "__main__":
    unittest.main()
