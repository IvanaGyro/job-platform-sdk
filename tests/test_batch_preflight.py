"""First-step 104 batch preflight: no writes and no private request bodies."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from job_platforms.core.errors import ConflictError, UnsupportedWrite
from job_platforms.providers.tw104.batch_preflight import preview_native_batch
from test_batch_edit import SKILL1, SKILL2, PATCH, THEME, SORT
from test_skill_records import Client as SkillClient
from test_language_records import Client as LanguageClient
from test_layout_theme import Client as ThemeClient
from test_bio_writer import WriterClient as BioClient


class BatchPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_skill_client_first_step_then_deferred(self):
        client = SkillClient()
        result = await client.plan_batch("synthetic", [SKILL1, SKILL2],
                                         expected_timestamp=123)
        self.assertEqual(result["steps"], [
            {"label": "1:skill.update", "status": "eligible_on_current_snapshot"},
            {"label": "2:skill.delete", "status": "deferred_pending_prior_steps"},
        ])
        self.assertEqual(result["resumeTimestamp"], 123)
        self.assertFalse(result["all_steps_dynamically_verified"])
        self.assertFalse(result["persisted"])
        self.assertFalse(result["network_write_sent"])
        self.assertFalse(result["current_site_write_success_verified"])
        self.assertEqual(client.transport.calls, [])
        self.assertNotIn(SKILL1["changes"]["desc"], str(result))
        self.assertNotIn("Python", str(result))

    async def test_bad_first_step_is_rejected_even_when_later_step_valid(self):
        client = SkillClient()
        invalid = {**SKILL1, "position": 200}
        with self.assertRaises(UnsupportedWrite):
            await client.plan_batch("synthetic", [invalid, SKILL2],
                                    expected_timestamp=123)
        self.assertEqual(client.transport.calls, [])

    async def test_invalid_later_step_is_rejected_before_any_reads(self):
        client = SkillClient()
        with patch.object(client, "get_resume", side_effect=AssertionError("No GET")):
            with self.assertRaises(UnsupportedWrite):
                await client.plan_batch("synthetic", [SKILL1, {
                    "type": "record", "section": "under18", "action": "delete",
                }], expected_timestamp=123)
        self.assertEqual(client.transport.calls, [])

    async def test_version_mismatch_aborts_before_body_check(self):
        client = SkillClient()
        with self.assertRaises(ConflictError):
            await client.plan_batch("synthetic", [SKILL1], expected_timestamp=122)
        self.assertEqual(client.transport.calls, [])

    async def test_sort_on_real_two_skill_records_is_source_checked(self):
        client = SkillClient()
        result = await client.plan_batch("synthetic", [SORT], expected_timestamp=123)
        self.assertEqual(result["checked_first_step_write_request_upper_bound"], 1)
        self.assertTrue(result["all_steps_dynamically_verified"])
        self.assertEqual(client.transport.calls, [])
        invalid = {**SORT, "to_position": 3}
        with self.assertRaises(UnsupportedWrite):
            await client.plan_batch("synthetic", [invalid], expected_timestamp=123)

    async def test_theme_options_are_checked_against_current_catalog(self):
        client = ThemeClient()
        result = await client.plan_batch("synthetic", [THEME],
                                         expected_timestamp=42)
        self.assertEqual(result["steps"][0]["status"],
                         "eligible_on_current_snapshot")
        self.assertEqual(client.transport.calls, [])
        with self.assertRaises(UnsupportedWrite):
            await client.plan_batch("synthetic", [{**THEME, "selected_theme": 999}],
                                    expected_timestamp=42)
        self.assertEqual(client.transport.calls, [])

    async def test_patch_native_preflight_without_put(self):
        client = BioClient()
        patch = {"type": "patch", "operations": [
            {"op": "replace", "path": "/bio/formData/bio/eng", "value": "<p>New</p>"},
        ]}
        result = await client.plan_batch("test123", [patch],
                                         expected_timestamp=100)
        self.assertEqual(result["checked_first_step_write_request_upper_bound"], 1)
        self.assertEqual(result["step_count"] if "step_count" in result else
                         len(result["steps"]), 1)
        self.assertNotIn("<p>New</p>", str(result))
        self.assertEqual(client.transport.calls, [])
        bad = {"type": "patch", "operations": [
            {"op": "replace", "path": "/bio/formData/bio/eng",
             "value": {"not": "a string"}},
        ]}
        with self.assertRaises(UnsupportedWrite):
            await client.plan_batch("test123", [bad], expected_timestamp=100)
        self.assertEqual(client.transport.calls, [])

    async def test_synthetic_language_update_with_source_selector_choices(self):
        client = LanguageClient()
        # The same official current options required by the real language SDK.
        first = {"type": "record", "section": "language", "kind": "local",
                 "action": "update", "position": 1,
                 "changes": {"level": {"text": "精通", "value": 2}}}
        result = await client.plan_batch("synthetic", [first],
                                         expected_timestamp=100)
        self.assertTrue(result["all_steps_dynamically_verified"])
        self.assertEqual(client.transport.calls, [])
        invalid = deepcopy(first)
        invalid["changes"]["level"]["text"] = "Unknown label"
        with self.assertRaises(UnsupportedWrite):
            await client.plan_batch("synthetic", [invalid], expected_timestamp=100)
        self.assertEqual(client.transport.calls, [])


if __name__ == "__main__":
    unittest.main()
