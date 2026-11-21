"""Synthetic tests only. No credentials or 104 account access."""
import unittest

from job_platforms.core.patch import (
    JsonPatchOperation, apply_json_patch, describe_schema,
)


class PatchTests(unittest.TestCase):
    def test_update_multiple_sections_without_mutating_original(self):
        original = {
            "info": {"formData": {"info": {"motto": "old"}}},
            "experience": {"formData": {"experiences": [
                {"jobName": "Engineer", "description": "before"}
            ]}},
        }
        updated = apply_json_patch(original, [
            JsonPatchOperation("replace", "/info/formData/info/motto", "new"),
            JsonPatchOperation(
                "replace", "/experience/formData/experiences/0/description",
                "after",
            ),
            JsonPatchOperation(
                "add", "/experience/formData/experiences/-",
                {"jobName": "Scientist"},
            ),
        ])
        self.assertEqual(original["info"]["formData"]["info"]["motto"], "old")
        self.assertEqual(updated["info"]["formData"]["info"]["motto"], "new")
        self.assertEqual(
            updated["experience"]["formData"]["experiences"][0]["description"],
            "after",
        )
        self.assertEqual(
            len(updated["experience"]["formData"]["experiences"]), 2
        )

    def test_pointer_escaping(self):
        updated = apply_json_patch(
            {"info": {"a/b": {"~name": "old"}}},
            [JsonPatchOperation("replace", "/info/a~1b/~0name", "new")],
        )
        self.assertEqual(updated["info"]["a/b"]["~name"], "new")

    def test_test_operation_and_remove(self):
        changed = apply_json_patch(
            {"list": [1, 2, 3]},
            [JsonPatchOperation("test", "/list/0", 1),
             JsonPatchOperation("remove", "/list/1")],
        )
        self.assertEqual(changed, {"list": [1, 3]})

    def test_reject_invalid_patches(self):
        with self.assertRaises(ValueError):
            JsonPatchOperation.from_dict({"op": "copy", "path": "/a"})
        with self.assertRaises(ValueError):
            apply_json_patch({}, [JsonPatchOperation("add", "", {})])
        with self.assertRaises(KeyError):
            apply_json_patch({"a": {}}, [
                JsonPatchOperation("replace", "/a/missing", "value")
            ])

    def test_boolean_is_not_json_number_in_preconditions(self):
        original = {"flags": [True, {"nested": False}], "numeric": [1.0]}
        invalid = [1, {"nested": 0}]
        with self.assertRaisesRegex(ValueError, "test failed"):
            apply_json_patch(original, [
                JsonPatchOperation("test", "/flags", invalid),
                JsonPatchOperation("replace", "/flags/0", False),
            ])
        with self.assertRaisesRegex(ValueError, "test failed"):
            apply_json_patch(original, [
                JsonPatchOperation("test", "/flags/0", 1),
            ])
        # JSON numbers compare by numeric value, unlike booleans.
        apply_json_patch(original, [
            JsonPatchOperation("test", "/numeric/0", 1),
        ])

    def test_schema_does_not_include_values(self):
        schema = describe_schema({"info": {"name": "not-a-real-person"}})
        self.assertNotIn("not-a-real-person", str(schema))
        self.assertEqual(schema["properties"]["info"]["type"], "object")
