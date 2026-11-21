"""Synthetic tests of the 104 BIO write adapter. No real account access."""
import asyncio
import copy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.writers import bio_data, bio_request_body


BASE = {
    "resume": {"vno": "test123"},
    "resumeTimestamp": 100,
    "bio": {"formData": {"bio": {"chi": "<p>old Chinese text</p>",
                                 "eng": "<p>old English text</p>"}}},
}


class FakeTransport:
    def __init__(self, owner, *, apply=True):
        self.owner = owner
        self.calls = []
        self.apply = apply

    async def put_json(self, path, data, *, params):
        self.calls.append((path, copy.deepcopy(data), dict(params)))
        if self.apply:
            self.owner.doc["bio"]["formData"]["bio"] = copy.deepcopy(
                data["blockValueList"]["bio"]["bio"]
            )
            self.owner.doc["resumeTimestamp"] += 1
        return {"data": {}}


class WriterClient(Resume104Client):
    def __init__(self):
        self.doc = copy.deepcopy(BASE)
        self.transport = FakeTransport(self)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert str(resume_id) == "test123"
        return copy.deepcopy(self.doc)


class BioWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_field_change_in_one_put(self):
        client = WriterClient()
        plan = EditPlan("test123", 100, [
            JsonPatchOperation("replace", "/bio/formData/bio/chi", "<p>new Chinese</p>"),
            JsonPatchOperation("replace", "/bio/formData/bio/eng", "<p>new English</p>"),
        ])
        result = await client.save_edit(plan)
        self.assertTrue(result["persisted"])
        self.assertTrue(result["verified"])
        self.assertEqual(len(client.transport.calls), 1)
        path, payload, params = client.transport.calls[0]
        self.assertEqual(path, "/profile/ajax/resumeByBlock/bio")
        self.assertEqual(params, {"vno": "test123"})
        self.assertEqual(payload["blockValueList"]["bio"]["bio"],
                         {"chi": "<p>new Chinese</p>", "eng": "<p>new English</p>"})

    async def test_sibling_bio_value_preserved(self):
        client = WriterClient()
        plan = EditPlan("test123", 100, [
            JsonPatchOperation("replace", "/bio/formData/bio/chi", "<p>updated</p>")
        ])
        await client.save_edit(plan)
        self.assertEqual(bio_data(client.doc)["eng"], "<p>old English text</p>")

    async def test_unsupported_section_rejected_before_write(self):
        client = WriterClient()
        plan = EditPlan("test123", 100, [
            JsonPatchOperation("replace", "/info/formData/info/cellphone", "invalid"),
        ])
        with self.assertRaises(UnsupportedWrite):
            await client.save_edit(plan)
        self.assertEqual(client.transport.calls, [])

    async def test_stale_timestamp_rejected(self):
        client = WriterClient()
        plan = EditPlan("test123", 99, [
            JsonPatchOperation("replace", "/bio/formData/bio/chi", "<p>new</p>")
        ])
        with self.assertRaises(ConflictError):
            await client.save_edit(plan)
        self.assertEqual(client.transport.calls, [])

    async def test_identical_value_skips_write(self):
        client = WriterClient()
        plan = EditPlan("test123", 100, [
            JsonPatchOperation("replace", "/bio/formData/bio/eng", "<p>old English text</p>")
        ])
        result = await client.save_edit(plan)
        self.assertFalse(result["persisted"])
        self.assertEqual(client.transport.calls, [])

    async def test_readback_mismatch_not_retried(self):
        client = WriterClient()
        client.transport.apply = False
        plan = EditPlan("test123", 100, [
            JsonPatchOperation("replace", "/bio/formData/bio/eng", "<p>new</p>")
        ])
        with self.assertRaises(VerificationError):
            await client.save_edit(plan)
        self.assertEqual(len(client.transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
