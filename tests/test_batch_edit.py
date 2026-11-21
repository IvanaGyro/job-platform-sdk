"""Synthetic non-atomic 104 batch orchestration and fail-closed validation."""
from copy import deepcopy
import unittest

from job_platforms.core.errors import (
    ConflictError, PartialWriteError, UnsupportedWrite, VerificationError,
)
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.batch_edit import (
    validate_batch_steps, apply_native_batch,
)
from job_platforms.providers.tw104.client import Resume104Client
from test_skill_records import Client as SkillClient

SKILL1 = {"type": "record", "section": "skill", "action": "update",
          "position": 1, "changes": {"desc": "synthetic changed"}}
SKILL2 = {"type": "record", "section": "skill", "action": "delete", "position": 2}
PATCH = {"type": "patch", "operations": [
    {"op": "replace", "path": "/bio/formData/bio/eng", "value": "synthetic new"},
]}
THEME = {"type": "theme", "section": "skill", "selected_theme": 2}
SORT = {"type": "sort", "section": "skill", "from_position": 1, "to_position": 2}

class Fake:
    _version = staticmethod(Resume104Client._version)
    _edit_timestamp = staticmethod(Resume104Client._edit_timestamp)
    def __init__(self, *, interrupt=None, fail_on=None):
        self.doc = {"resumeTimestamp": 100, "bio": {"formData": {
            "bio": {"chi": "original", "eng": "original"}}},
                    "skill": {"formData": {"skills": ["synthetic"]}}}
        self.calls = []
        self.reads = 0
        self.interrupt = interrupt
        self.fail_on = fail_on

    async def apply_batch(self, resume_id, steps, *, expected_timestamp):
        return await apply_native_batch(
            self, resume_id, steps, expected_timestamp=expected_timestamp,
        )

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        self.reads += 1
        if self.interrupt == self.reads:
            self.doc["bio"]["formData"]["bio"]["chi"] = "external edit"
            self.doc["resumeTimestamp"] += 1
        return deepcopy(self.doc)

    def _commit(self, kind, timestamp):
        assert str(self.doc["resumeTimestamp"]) == str(timestamp)
        self.calls.append(kind)
        if self.fail_on == kind:
            raise VerificationError("Synthetic uncertain write")
        self.doc["resumeTimestamp"] += 1
        return {"persisted": True, "verified": True}

    async def mutate_skill(self, version, action, *, position=None,
                           changes=None, expected_timestamp):
        return self._commit("skill." + action, expected_timestamp)

    async def mutate_language(self, version, kind, action, *, position=None,
                              changes=None, expected_timestamp):
        return self._commit("language." + kind + "." + action, expected_timestamp)

    async def plan_edit(self, version, operations):
        self.calls.append("plan")
        return EditPlan(version, self.doc["resumeTimestamp"], [
            JsonPatchOperation.from_dict(op) for op in operations
        ]), deepcopy(self.doc)

    async def save_edit(self, plan):
        return self._commit("patch", plan.base_timestamp)

    async def set_theme(self, version, section, selected_theme, *, expected_timestamp):
        return self._commit("theme", expected_timestamp)

    async def sort_records(self, version, section, first, second, *,
                           kind=None, expected_timestamp):
        return self._commit("sort", expected_timestamp)

class BatchValidationTests(unittest.TestCase):
    def test_supported_steps_are_copied_and_ordered(self):
        steps = [SKILL1, SKILL2, PATCH, THEME, SORT,
                 {"type": "record", "section": "language", "kind": "foreign",
                  "action": "update", "position": 1,
                  "changes": {"level": "synthetic"}}]
        result = validate_batch_steps(steps)
        self.assertEqual(result, steps)
        self.assertIsNot(result[0], SKILL1)
        result[0]["changes"]["desc"] = "changed copy"
        self.assertEqual(SKILL1["changes"]["desc"], "synthetic changed")

    def test_fail_closed_unknown_actions_shapes_and_sensitive_fields(self):
        invalid = [None, {}, [], [True], [{}], [SKILL1]*13,
                   [{**SKILL1, "unknown": 1}],
                   [{**SKILL1, "section": "under18"}],
                   [{**SKILL1, "section": "portfolio"}],
                   [{**SKILL1, "action": "rename"}],
                   [{**SKILL1, "position": 0}],
                   [{**SKILL1, "position": True}],
                   [{**SKILL1, "changes": []}],
                   [{"type": "record", "section": "skill", "action": "create",
                     "position": 1, "changes": {"name": "bad"}}],
                   [{**SKILL2, "changes": {}}],
                   [{**SKILL1, "kind": "local"}],
                   [{"type": "record", "section": "language", "action": "create",
                     "changes": {"type": 1}}],
                   [{"type": "patch", "operations": []}],
                   [{"type": "patch", "operations": [
                     {"op": "test", "path": "/bio/formData/bio/chi", "value": "a"}]}],
                   [{"type": "patch", "operations": [
                     {"op": "replace", "path": "/under18/formData/x", "value": "a"}]}],
                   [{**THEME, "selected_theme": True}],
                   [{**THEME, "section": "under18"}],
                   [{**SORT, "to_position": 1}],
                   [{**SORT, "from_position": 0}],
                   [{**SORT, "kind": "foreign"}],
                   [{"type": "sort", "section": "language", "from_position": 1,
                     "to_position": 2}],
        ]
        for steps in invalid:
            with self.subTest(steps=str(steps)[:120]), self.assertRaises(UnsupportedWrite):
                validate_batch_steps(steps)

class BatchExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_patch_theme_sort_steps_refresh_revision(self):
        client = Fake()
        result = await apply_native_batch(client, "synthetic",
            [SKILL1, PATCH, THEME, SORT, SKILL2], expected_timestamp="100")
        self.assertEqual(result["verified_steps"], [
            "1:skill.update", "2:patch", "3:theme", "4:sort", "5:skill.delete",
        ])
        self.assertFalse(result["atomic"])
        self.assertEqual(result["step_count"], 5)
        self.assertEqual(client.doc["resumeTimestamp"], 105)
        self.assertEqual(client.calls,
                         ["skill.update", "plan", "patch", "theme", "sort", "skill.delete"])
        self.assertNotIn("synthetic changed", str(result))

    async def test_real_skill_sdk_two_native_puts_no_new_104_endpoints(self):
        client = SkillClient()
        result = await client.apply_batch("synthetic", [
            SKILL1, {**SKILL1, "changes": {"desc": "Second synthetic edit"}},
        ], expected_timestamp=123)
        self.assertEqual(result["verified_steps"], ["1:skill.update", "2:skill.update"])
        self.assertEqual([row[0] for row in client.transport.calls], ["PUT", "PUT"])
        self.assertEqual(client.doc["resumeTimestamp"], 125)

    async def test_no_104_mutation_when_later_step_has_invalid_shape(self):
        client = Fake()
        with self.assertRaises(UnsupportedWrite):
            await apply_native_batch(client, "synthetic", [
                SKILL1, {"type": "record", "section": "under18", "action": "delete"},
            ], expected_timestamp=100)
        self.assertEqual(client.calls, [])
        self.assertEqual(client.reads, 0)

    async def test_stale_initial_revision_blocks_all_actions(self):
        client = Fake()
        with self.assertRaises(ConflictError):
            await apply_native_batch(client, "synthetic", [SKILL1],
                                     expected_timestamp="99")
        self.assertEqual(client.calls, [])

    async def test_unexpected_external_change_between_steps_aborts_next_write(self):
        # GET 1: initial, GET 2: post-step verified snapshot, GET 3: next-step preflight
        client = Fake(interrupt=3)
        with self.assertRaises(PartialWriteError) as err:
            await apply_native_batch(client, "synthetic", [SKILL1, SKILL2],
                                     expected_timestamp=100)
        self.assertEqual(err.exception.verified_sections, ["1:skill.update"])
        self.assertEqual(err.exception.failed_section, "2:skill.delete")
        self.assertEqual(client.calls, ["skill.update"])

    async def test_external_sibling_change_during_post_step_get_fails_closed(self):
        client = Fake(interrupt=2)
        with self.assertRaises(VerificationError):
            await apply_native_batch(client, "synthetic", [SKILL1, SKILL2],
                                     expected_timestamp=100)
        # The first write was sent. No second operation, no automatic retry.
        self.assertEqual(client.calls, ["skill.update"])

    async def test_external_data_change_without_revision_also_aborts(self):
        client = Fake()
        original_get = client.get_resume
        async def change_without_version(version):
            snapshot = await original_get(version)
            if client.reads == 3:
                snapshot["bio"]["formData"]["bio"]["chi"] = "external without timestamp"
            return snapshot
        client.get_resume = change_without_version
        with self.assertRaises(PartialWriteError):
            await apply_native_batch(client, "synthetic", [SKILL1, SKILL2],
                                     expected_timestamp=100)
        self.assertEqual(client.calls, ["skill.update"])

    async def test_later_upstream_uncertainty_not_retried(self):
        client = Fake(fail_on="skill.delete")
        with self.assertRaises(PartialWriteError) as err:
            await apply_native_batch(client, "synthetic", [SKILL1, SKILL2],
                                     expected_timestamp=100)
        self.assertEqual(err.exception.verified_sections, ["1:skill.update"])
        self.assertEqual(err.exception.failed_section, "2:skill.delete")
        self.assertEqual(client.calls, ["skill.update", "skill.delete"])

    async def test_first_step_error_propagates_without_partial_claim(self):
        client = Fake(fail_on="skill.update")
        with self.assertRaises(VerificationError):
            await apply_native_batch(client, "synthetic", [SKILL1, SKILL2],
                                     expected_timestamp=100)
        self.assertEqual(client.calls, ["skill.update"])

    async def test_unverified_noop_cannot_be_described_as_batch_success(self):
        client = Fake()
        async def no_change(*_, **__):
            return {"verified": True, "persisted": False}
        client.mutate_skill = no_change
        with self.assertRaises(VerificationError):
            await apply_native_batch(client, "synthetic", [SKILL1],
                                     expected_timestamp=100)


if __name__ == "__main__":
    unittest.main()
