"""Read-after-write must reject correct target values with collateral data loss."""
from copy import deepcopy
import unittest

from job_platforms.core.errors import PartialWriteError, VerificationError
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.patch_verification import (
    stable_block_equal, verify_patch_transition,
)
from job_platforms.providers.tw104.writers import section_data
from test_seniority import BASE as SENIORITY, Client as SeniorityClient
from test_certificate_multisection import BASE as MULTI, WriterClient
from test_sidebar import BASE as SIDEBAR


def file_or_link(kind: int, sort: int) -> dict:
    return {
        "name": f"Synthetic {sort}", "sort": sort,
        "attachType": {"value": kind, "text": "File" if kind == 1 else "Link"},
        "attach": {
            "name": f"item{sort}.pdf", "status": 1, "url": "https://example.invalid/link",
            "fileId": "opaque-file-a", "thumbnailFileId": "opaque-thumbnail-a",
            "src": "https://example.invalid/opaque-a", "crawler": False,
        },
    }


class PatchPreservationTests(unittest.IsolatedAsyncioTestCase):
    def test_correct_seniority_does_not_mask_erased_experience_records(self):
        before = deepcopy(SENIORITY)
        after = deepcopy(before)
        after["experience"]["formData"]["seniority"] = {
            "text": "Server display label", "value": 3,
        }
        self.assertTrue(verify_patch_transition(
            before, after, "experience", {"value": 3},
        ))
        after["experience"]["formData"]["experiences"] = []
        self.assertFalse(verify_patch_transition(
            before, after, "experience", {"value": 3},
        ))

    def test_correct_bio_value_does_not_mask_missing_metadata_or_other_block(self):
        before = deepcopy(MULTI)
        before["bio"]["formData"]["displayRule"] = {"show": True}
        after = deepcopy(before)
        after["bio"]["formData"]["bio"]["chi"] = "Changed"
        desired = {"chi": "Changed", "eng": "hello"}
        self.assertTrue(verify_patch_transition(before, after, "bio", desired))
        damaged = deepcopy(after)
        del damaged["bio"]["formData"]["displayRule"]
        self.assertFalse(verify_patch_transition(before, damaged, "bio", desired))
        damaged = deepcopy(after)
        damaged["certificate"]["formData"]["certificate"]["others"] = "clobbered"
        self.assertFalse(verify_patch_transition(before, damaged, "bio", desired))

    def test_certificate_other_text_preserves_native_associations(self):
        before = deepcopy(MULTI)
        after = deepcopy(before)
        after["certificate"]["formData"]["certificate"]["others"] = "updated"
        desired = deepcopy(section_data(after, "certificate"))
        self.assertTrue(verify_patch_transition(before, after, "certificate", desired))
        after["certificate"]["formData"]["certificate"]["certifications"] = []
        self.assertFalse(verify_patch_transition(before, after, "certificate", desired))

    def test_sidebar_correct_ids_do_not_mask_damaged_metadata(self):
        before = deepcopy(SIDEBAR)
        after = deepcopy(before)
        after["sidebar"].reverse()
        ids = {"ids": [x["id"] for x in after["sidebar"]]}
        self.assertTrue(verify_patch_transition(before, after, "sidebar", ids))
        after["sidebar"][-1].pop("customMeta")
        self.assertFalse(verify_patch_transition(before, after, "sidebar", ids))

    def test_portfolio_file_token_rotation_allowed_but_link_target_protected(self):
        before = {"portfolio": {"formData": {
            "themeChoose": {"selectedTheme": {"value": 1}},
            "portfolios": [file_or_link(1, 1), file_or_link(2, 2)],
        }}}
        rotated = deepcopy(before)
        file = rotated["portfolio"]["formData"]["portfolios"][0]["attach"]
        for field in ("fileId", "thumbnailFileId", "src", "url"):
            file[field] = "regenerated-access-token"
        self.assertTrue(stable_block_equal(before, rotated, "portfolio"))
        rotated["portfolio"]["formData"]["portfolios"][1]["attach"]["url"] = "https://example.invalid/different-link"
        self.assertFalse(stable_block_equal(before, rotated, "portfolio"))

    async def test_seniority_put_damaging_experiences_is_not_verified(self):
        client = SeniorityClient()
        original_put = client.transport.put_json
        async def corrupt_put(path, data, *, params):
            result = await original_put(path, data, params=params)
            client.doc["experience"]["formData"]["experiences"].clear()
            return result
        client.transport.put_json = corrupt_put
        with self.assertRaises(VerificationError):
            await client.save_edit(EditPlan("synthetic", 123, [
                JsonPatchOperation("replace", "/experience/formData/seniority/value", 3)
            ]))
        self.assertEqual(len(client.transport.calls), 1)

    async def test_fresh_get_rejects_metadata_only_external_revision(self):
        client = WriterClient()
        original_get = client.get_resume
        count = 0
        async def mutate_revision_after_verified_snapshot(version):
            nonlocal count
            count += 1
            doc = await original_get(version)
            if count == 2:
                # An untracked external editor changes a resume-level
                # setting, not any section in PRESERVE_BLOCKS.
                client.doc["resumeTimestamp"] += 1
            return doc
        client.get_resume = mutate_revision_after_verified_snapshot
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation("replace", "/bio/formData/bio/chi", "Updated"),
            JsonPatchOperation("replace", "/certificate/formData/certificate/others", "Updated"),
        ])
        with self.assertRaises(PartialWriteError) as context:
            await client.save_edit(plan)
        self.assertEqual(context.exception.verified_sections, ["bio"])
        self.assertEqual(context.exception.failed_section, "certificate")
        self.assertEqual(len(client.transport.calls), 1)
        self.assertGreaterEqual(count, 3)

    async def test_multi_section_save_allows_only_known_file_token_rotation(self):
        client = WriterClient()
        file = file_or_link(1, 1)
        client.doc["portfolio"] = {"formData": {
            "themeChoose": {"selectedTheme": {"value": 1}},
            "portfolios": [file],
        }}
        native_get = client.get_resume
        reads = 0
        async def rotating_access_url(version):
            nonlocal reads
            reads += 1
            doc = await native_get(version)
            attached = doc["portfolio"]["formData"]["portfolios"][0]["attach"]
            for key in ("fileId", "thumbnailFileId", "src", "url"):
                attached[key] = f"access-token-{reads}-{key}"
            return doc
        client.get_resume = rotating_access_url
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation("replace", "/bio/formData/bio/chi", "Updated"),
            JsonPatchOperation("replace", "/certificate/formData/certificate/others", "Updated"),
        ])
        result = await client.save_edit(plan)
        self.assertEqual(result["verified_sections"], ["bio", "certificate"])
        self.assertGreaterEqual(reads, 4)
        self.assertEqual(len(client.transport.calls), 2)
        self.assertEqual(client.doc["portfolio"]["formData"]["portfolios"][0], file)

    async def test_fresh_get_before_second_put_detects_new_external_change(self):
        client = WriterClient()
        original_get = client.get_resume
        count = 0
        async def externally_edit_after_first_verified_readback(version):
            nonlocal count
            count += 1
            snapshot = await original_get(version)
            if count == 2:
                # Initial GET=1. First BIO PUT completes, then GET #2
                # returns the verified BIO and an unchanged certificate.
                # Another browser concurrently changes the certificate
                # *after* that snapshot but *before* our second PUT.
                client.doc["certificate"]["formData"]["certificate"][
                    "others"
                ] = "New value from another editor"
                client.doc["resumeTimestamp"] += 1
            return snapshot
        client.get_resume = externally_edit_after_first_verified_readback
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation("replace", "/bio/formData/bio/chi", "changed"),
            JsonPatchOperation("replace", "/certificate/formData/certificate/others", "updated"),
        ])
        with self.assertRaises(PartialWriteError) as context:
            await client.save_edit(plan)
        self.assertEqual(context.exception.verified_sections, ["bio"])
        self.assertEqual(context.exception.failed_section, "certificate")
        self.assertEqual([x[0].rsplit("/", 1)[-1] for x in client.transport.calls], ["bio"])
        self.assertGreaterEqual(count, 3, "Second PUT must perform a fresh GET")
        self.assertEqual(client.doc["certificate"]["formData"]["certificate"]["others"],
                         "New value from another editor")

    async def test_second_put_clobbering_first_raises_partial_write(self):
        client = WriterClient()
        original_put = client.transport.put_json
        async def corrupt_second(path, data, *, params):
            response = await original_put(path, data, params=params)
            if path.endswith("/certificate"):
                client.doc["bio"]["formData"]["bio"]["chi"] = "clobbered"
            return response
        client.transport.put_json = corrupt_second
        plan = EditPlan("synthetic-id", 123, [
            JsonPatchOperation("replace", "/bio/formData/bio/eng", "changed"),
            JsonPatchOperation("replace", "/certificate/formData/certificate/others", "updated"),
        ])
        with self.assertRaises(PartialWriteError) as context:
            await client.save_edit(plan)
        self.assertEqual(context.exception.verified_sections, ["bio"])
        self.assertEqual(context.exception.failed_section, "certificate")
        self.assertEqual(len(client.transport.calls), 2)


if __name__ == "__main__":
    unittest.main()
