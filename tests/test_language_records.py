"""Synthetic 104 LANGUAGE local/foreign CRUD and safe readback tests."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.language_records import (
    language_lists, language_operation_body, verify_language_operation,
)

LOCAL = {"type": {"text": "Taiwanese Hokkien", "value": 1},
         "level": {"text": "Fluent", "value": 4}, "sort": 1}
FOREIGN = {
    "type": {"text": "English", "value": 1},
    "listening": {"text": "Fluent", "value": 4},
    "speaking": {"text": "Good", "value": 3},
    "reading": {"text": "Fluent", "value": 4},
    "writing": {"text": "Good", "value": 3},
    "certificate": [], "sort": 1,
}
BASE = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "language": {"formData": {
        "themeChoose": {"selectedTheme": {"text": "List", "value": 1}},
        "languages": {"foreign": [deepcopy(FOREIGN)], "local": [deepcopy(LOCAL)]},
    }},
}


class Transport:
    def __init__(self, owner, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.ambiguous = ambiguous

    async def request(self, method, path, *, params, json_data):
        assert path == "/profile/ajax/resumeByBlock/language"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        buckets = json_data["blockValueList"]["language"]["languages"]
        kind = next(k for k in ("local", "foreign")
                    if (isinstance(buckets[k], dict) and buckets[k].get("sort")) or (isinstance(buckets[k], list) and buckets[k]))
        records = self.owner.doc["language"]["formData"]["languages"][kind]
        if method == "POST":
            wire = buckets[kind][0]
            template = deepcopy(LOCAL if kind == "local" else FOREIGN)
            for key, value in wire.items():
                template[key] = {"text": str(value), "value": value}
            template["sort"] = len(records) + 1
            records.append(template)
        elif method == "PUT":
            wire = buckets[kind][0]
            template = records[wire["sort"] - 1]
            for key, value in wire.items():
                if key != "sort":
                    template[key] = {"text": str(value), "value": value}
        elif method == "DELETE":
            records.pop(buckets[kind]["sort"][0] - 1)
            for i, row in enumerate(records, 1):
                row["sort"] = i
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Simulated lost response")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, ambiguous=False):
        self.doc = deepcopy(BASE)
        self.transport = Transport(self, ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class LanguageTests(unittest.IsolatedAsyncioTestCase):
    def test_create_update_delete_native_buckets(self):
        foreign_fields = {k: deepcopy(v) for k, v in FOREIGN.items() if k not in ("certificate", "sort")}
        foreign_fields["type"] = {"text": "Japanese", "value": 2}
        body = language_operation_body(BASE, "foreign", "create", changes=foreign_fields)
        self.assertEqual(
            body["blockValueList"]["language"]["languages"]["foreign"],
            [{"type": 2, "listening": 4, "speaking": 3, "reading": 4, "writing": 3}],
        )
        self.assertEqual(body["blockValueList"]["language"]["languages"]["local"], [])
        self.assertEqual(
            language_operation_body(
                BASE, "local", "update", position=1,
                changes={"level": {"text": "Good", "value": 3}},
            )["blockValueList"]["language"]["languages"]["local"][0]["sort"], 1
        )
        self.assertEqual(
            language_operation_body(BASE, "foreign", "delete", position=1),
            {"blockValueList": {"language": {"languages": {
                "foreign": {"sort": [1]}, "local": {"sort": []},
            }}}},
        )
        self.assertEqual(list(language_lists(BASE)), ["foreign", "local"])

    def test_rejects_unknown_and_certificate_destruction(self):
        for kind, action, fields, pos in (
            ("foreign", "create", {"type": FOREIGN["type"]}, None),
            ("local", "create", {"level": LOCAL["level"]}, None),
            ("foreign", "update", {"certificate": []}, 1),
            ("foreign", "update", {"type": {"text": "bad", "value": None}}, 1),
            ("bad", "delete", None, 1),
            ("foreign", "delete", None, 5),
        ):
            with self.subTest(kind=kind, action=action):
                with self.assertRaises(UnsupportedWrite):
                    language_operation_body(BASE, kind, action, changes=fields, position=pos)
        doc = deepcopy(BASE)
        doc["language"]["formData"]["languages"]["foreign"][0]["certificate"].append({"id": 1})
        with self.assertRaises(UnsupportedWrite):
            language_operation_body(doc, "foreign", "delete", position=1)
        with self.assertRaises(UnsupportedWrite):
            language_operation_body(doc, "foreign", "update", position=1,
                                    changes={"speaking": {"text": "OK", "value": 2}})

    def test_duplicate_type_create_is_rejected_before_wire_serialization(self):
        for kind, record, ignored in (
            ("foreign", FOREIGN, {"certificate", "sort"}),
            ("local", LOCAL, {"sort"}),
        ):
            with self.subTest(kind=kind):
                duplicate = {key: deepcopy(value) for key, value in record.items()
                             if key not in ignored}
                with self.assertRaisesRegex(UnsupportedWrite, "may overwrite"):
                    language_operation_body(BASE, kind, "create", changes=duplicate)
                duplicate["type"]["value"] = str(record["type"]["value"])
                with self.assertRaisesRegex(UnsupportedWrite, "may overwrite"):
                    language_operation_body(BASE, kind, "create", changes=duplicate)

    def test_type_id_normalization_does_not_bypass_duplicate_guard(self):
        changes = {key: deepcopy(value) for key, value in FOREIGN.items()
                   if key not in {"certificate", "sort"}}
        for raw in ("1", "01", "+1", "1.0", 0, -1, "一", True):
            with self.subTest(raw=raw):
                changes["type"]["value"] = raw
                with self.assertRaises(UnsupportedWrite):
                    language_operation_body(BASE, "foreign", "create", changes=changes)

    async def test_duplicate_foreign_type_create_never_sends_http_request(self):
        client = Client()
        existing = {key: deepcopy(value) for key, value in FOREIGN.items()
                    if key not in {"certificate", "sort"}}
        with self.assertRaises(UnsupportedWrite):
            await client.mutate_language(
                "synthetic", "foreign", "create", expected_timestamp=100,
                changes=existing,
            )
        self.assertEqual(client.transport.calls, [])
        self.assertEqual(client.doc, BASE)

    async def test_local_update_and_foreign_create_delete(self):
        client = Client()
        changed = await client.mutate_language(
            "synthetic", "local", "update", position=1, expected_timestamp=100,
            changes={"level": {"text": "Excellent", "value": 5}},
        )
        self.assertTrue(changed["verified"])
        fields = {k: deepcopy(v) for k, v in FOREIGN.items() if k not in ("certificate", "sort")}
        fields["type"] = {"text": "Japanese", "value": 2}
        created = await client.mutate_language(
            "synthetic", "foreign", "create", expected_timestamp=client.doc["resumeTimestamp"],
            changes=fields,
        )
        self.assertEqual(created["position"], 2)
        deleted = await client.mutate_language(
            "synthetic", "foreign", "delete", position=2,
            expected_timestamp=client.doc["resumeTimestamp"],
        )
        self.assertTrue(deleted["verified"])
        self.assertEqual([x[0] for x in client.transport.calls], ["PUT", "POST", "DELETE"])

    async def test_stale_and_lost_response_do_not_retry(self):
        client = Client()
        with self.assertRaises(ConflictError):
            await client.mutate_language(
                "synthetic", "local", "delete", position=1, expected_timestamp=99
            )
        self.assertEqual(client.transport.calls, [])
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.mutate_language(
                "synthetic", "local", "delete", position=1, expected_timestamp=100
            )
        self.assertEqual(len(client.transport.calls), 1)

    def test_unrelated_language_branch_change_fails_verification(self):
        before = deepcopy(BASE)
        after = deepcopy(before)
        after["language"]["formData"]["languages"]["local"][0]["level"]["value"] = 2
        body = language_operation_body(
            before, "foreign", "update", position=1,
            changes={"speaking": {"text": "Excellent", "value": 5}}
        )
        after["language"]["formData"]["languages"]["foreign"][0]["speaking"] = {
            "text": "Excellent", "value": 5
        }
        self.assertFalse(verify_language_operation(
            before, after, "foreign", "update", body=body, position=1
        ))


if __name__ == "__main__":
    unittest.main()
