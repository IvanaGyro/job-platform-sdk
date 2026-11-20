"""Public synthetic tests: native input metadata, no actual account values."""
from copy import deepcopy
import unittest

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.editor_limits import (
    INPUT_FIELD_GROUPS, native_editor_limits,
)


SYNTHETIC_SITE_RULES = {
    "language": {
        "foreign": {"count": 7, "regex": "secret-or-sensitive-text", "type": {
            "maxLength": 40, "allowedValues": ["private value"]}},
        "local": {"count": 3, "required": True, "example": "private"},
    },
    "projects": {
        "count": 6, "name": {"maxLength": 120, "minLength": 1},
        "introduction": {"maxLength": 2000, "htmlMaxLength": 4000},
        "demoPersonalField": {"text": "not-an-editor-limit", "options": ["secret"]},
    },
    "info": {"nickname": {"maxLength": 30}, "secret": "synthetic-sensitive"},
    "customs": {},
}


class DummyTransport:
    def __init__(self):
        self.gets = []
        self.writes = []

    async def get_json(self, path):
        self.gets.append(path)
        if path != "/profile/ajax/inputField":
            raise AssertionError("unexpected path")
        return {"data": deepcopy(SYNTHETIC_SITE_RULES)}

    async def request(self, method, path, **kwargs):
        self.writes.append((method, path))
        raise AssertionError("read-only method may not write")


class EditorLimitsTests(unittest.IsolatedAsyncioTestCase):
    def test_native_sanitizer_preserves_only_numeric_and_boolean_rules(self):
        language = native_editor_limits(SYNTHETIC_SITE_RULES, "language")
        self.assertEqual(language["source_group"], "language")
        self.assertEqual(language["constraints"], {
            "foreign": {"count": 7, "type": {"maxLength": 40}},
            "local": {"count": 3, "required": True},
        })
        self.assertTrue(language["read_only"])
        self.assertFalse(language["persisted"])
        self.assertNotIn("private", str(language))
        project = native_editor_limits(SYNTHETIC_SITE_RULES, "project")
        self.assertEqual(project["source_group"], "projects")
        self.assertEqual(project["constraints"]["name"]["maxLength"], 120)
        self.assertEqual(project["constraints"]["introduction"]["htmlMaxLength"], 4000)
        self.assertNotIn("demoPersonalField", project["constraints"])
        self.assertFalse(native_editor_limits(SYNTHETIC_SITE_RULES, "custom")["limits_available"])

    def test_unknown_or_missing_groups_fail_closed(self):
        for section in ("user", "under18", "__proto__", ""):
            with self.subTest(section=section), self.assertRaises(UnsupportedWrite):
                native_editor_limits(SYNTHETIC_SITE_RULES, section)
        for section in INPUT_FIELD_GROUPS:
            if INPUT_FIELD_GROUPS[section] not in SYNTHETIC_SITE_RULES:
                with self.subTest(section=section), self.assertRaises(UnsupportedWrite):
                    native_editor_limits(SYNTHETIC_SITE_RULES, section)

    def test_invalid_rules_never_echo_external_strings_or_unbounded_numbers(self):
        rules = deepcopy(SYNTHETIC_SITE_RULES)
        rules["language"]["foreign"].update({
            "maxLength": True, "count": 2**64, "minLength": -2,
            "required": 1, "email": "user@example.invalid",
            "extraArray": [{"maxLength": 8}],
        })
        output = native_editor_limits(rules, "language")
        self.assertNotIn("count", output["constraints"]["foreign"])
        self.assertNotIn("maxLength", output["constraints"]["foreign"])
        self.assertNotIn("minLength", output["constraints"]["foreign"])
        self.assertNotIn("required", output["constraints"]["foreign"])
        self.assertNotIn("example.invalid", str(output))
        huge = deepcopy(SYNTHETIC_SITE_RULES)
        huge["language"] = {f"field{i}": {"count": 1} for i in range(1100)}
        with self.assertRaises(UnsupportedWrite):
            native_editor_limits(huge, "language")

    async def test_client_is_read_only_and_requires_official_group(self):
        transport = DummyTransport()
        client = Resume104Client(transport=transport)
        result = await client.get_editor_limits("project")
        self.assertEqual(result["constraints"]["count"], 6)
        self.assertEqual(transport.gets, ["/profile/ajax/inputField"])
        self.assertEqual(transport.writes, [])
        with self.assertRaises(UnsupportedWrite):
            await client.get_editor_limits("unmapped")
        self.assertEqual(transport.gets, ["/profile/ajax/inputField"])


if __name__ == "__main__":
    unittest.main()
