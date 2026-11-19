"""Synthetic 104 LANGUAGE local/foreign CRUD and safe readback tests."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.language_records import (
    language_lists, language_operation_body, validate_language_selectors,
    verify_language_operation,
)

LOCAL = {"type": {"text": "台語", "value": 1},
         "level": {"text": "略懂", "value": 4}, "sort": 1}
FOREIGN = {
    "type": {"text": "英文", "value": 1},
    "listening": {"text": "精通", "value": 2},
    "speaking": {"text": "略懂", "value": 4},
    "reading": {"text": "精通", "value": 2},
    "writing": {"text": "略懂", "value": 4},
    "certificate": [], "sort": 1,
}
# Public, source-mapped subset of the 104 editor option catalog. No user data.
OPTIONS = {
    "optionsForeignType": [{"text": "英文", "value": 1}, {"text": "日文", "value": 2}],
    "optionsLocalType": [{"text": "台語", "value": 1}, {"text": "客語", "value": 2}],
    "optionsLanguageForeignLevel": [
        {"text": "不會", "value": 1}, {"text": "略懂", "value": 4},
        {"text": "中等", "value": 8}, {"text": "精通", "value": 2},
    ],
    "optionsLanguageLocalLevel": [
        {"text": "略懂", "value": 4}, {"text": "中等", "value": 8},
        {"text": "精通", "value": 2},
    ],
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

    async def get_json(self, path):
        if path != "/profile/ajax/options":
            raise AssertionError(path)
        return {"data": deepcopy(OPTIONS)}

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


class OverwritingTransport(Transport):
    """Synthetic upstream anomaly: POST edits the first row, not append."""

    async def request(self, method, path, *, params, json_data):
        if method != "POST":
            return await super().request(method, path, params=params, json_data=json_data)
        self.calls.append((method, deepcopy(json_data)))
        wire = json_data["blockValueList"]["language"]["languages"]["foreign"][0]
        row = self.owner.doc["language"]["formData"]["languages"]["foreign"][0]
        for field, value in wire.items():
            row[field] = {"text": str(value), "value": value}
        self.owner.doc["resumeTimestamp"] += 1
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
        foreign_fields["type"] = {"text": "日文", "value": 2}
        body = language_operation_body(BASE, "foreign", "create", changes=foreign_fields)
        self.assertEqual(
            body["blockValueList"]["language"]["languages"]["foreign"],
            [{"type": 2, "listening": 2, "speaking": 4, "reading": 2, "writing": 4}],
        )
        self.assertEqual(body["blockValueList"]["language"]["languages"]["local"], [])
        self.assertEqual(
            language_operation_body(
                BASE, "local", "update", position=1,
                changes={"level": {"text": "精通", "value": 2}},
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

    async def test_update_to_other_existing_language_is_rejected_before_http(self):
        client = Client()
        second = deepcopy(FOREIGN)
        second["type"] = {"text": "日文", "value": 2}
        second["sort"] = 2
        client.doc["language"]["formData"]["languages"]["foreign"].append(second)
        before = deepcopy(client.doc)
        with self.assertRaisesRegex(UnsupportedWrite, "collide"):
            await client.mutate_language(
                "synthetic", "foreign", "update", position=2,
                expected_timestamp=100,
                changes={"type": {"text": "英文", "value": "1"}},
            )
        self.assertEqual(client.transport.calls, [])
        self.assertEqual(client.doc, before)

    async def test_unexpected_upstream_create_overwrite_is_not_verified_or_retried(self):
        client = Client()
        client.transport = OverwritingTransport(client)
        before = deepcopy(client.doc)
        changes = {key: deepcopy(value) for key, value in FOREIGN.items()
                   if key not in {"certificate", "sort"}}
        changes["type"] = {"text": "日文", "value": 2}
        with self.assertRaises(VerificationError):
            await client.mutate_language(
                "synthetic", "foreign", "create", expected_timestamp=100,
                changes=changes,
            )
        self.assertEqual(len(client.transport.calls), 1)
        self.assertEqual(client.transport.calls[0][0], "POST")
        self.assertEqual(len(client.doc["language"]["formData"]["languages"]["foreign"]), 1)
        self.assertNotEqual(client.doc, before)

    def test_uses_distinct_official_option_catalogs_for_foreign_and_local(self):
        validate_language_selectors(OPTIONS, "foreign", {
            "type": {"text": "日文", "value": "2"},
            "speaking": {"text": "中等", "value": 8},
        })
        validate_language_selectors(OPTIONS, "local", {
            "type": {"text": "客語", "value": 2},
            "level": {"text": "精通", "value": 2},
        })
        for kind, bad in (
            ("foreign", {"type": {"text": "外文", "value": 1}}),
            ("foreign", {"type": {"text": "日文", "value": 1}}),
            ("foreign", {"type": {"text": "日文", "value": 999}}),
            ("local", {"type": {"text": "日文", "value": 2}}),
            ("local", {"level": {"text": "不會", "value": 1}}),
        ):
            with self.subTest(kind=kind, bad=bad):
                with self.assertRaises(UnsupportedWrite):
                    validate_language_selectors(OPTIONS, kind, bad)
        with self.assertRaises(UnsupportedWrite):
            validate_language_selectors({}, "foreign", {"type": {"text": "日文", "value": 2}})
        bool_options = deepcopy(OPTIONS)
        bool_options["optionsForeignType"] = [{"text": "英文", "value": True}]
        with self.assertRaises(UnsupportedWrite):
            validate_language_selectors(bool_options, "foreign", {"type": {"text": "英文", "value": 1}})

    async def test_wrong_current_site_language_options_fail_before_http(self):
        client = Client()
        with self.assertRaises(UnsupportedWrite):
            await client.mutate_language(
                "synthetic", "local", "update", position=1,
                expected_timestamp=100,
                changes={"type": {"text": "客語", "value": 1}},
            )
        self.assertEqual(client.transport.calls, [])
        self.assertEqual(client.doc, BASE)

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
            changes={"level": {"text": "精通", "value": 2}},
        )
        self.assertTrue(changed["verified"])
        fields = {k: deepcopy(v) for k, v in FOREIGN.items() if k not in ("certificate", "sort")}
        fields["type"] = {"text": "日文", "value": 2}
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
            changes={"speaking": {"text": "精通", "value": 2}}
        )
        after["language"]["formData"]["languages"]["foreign"][0]["speaking"] = {
            "text": "精通", "value": 2
        }
        self.assertFalse(verify_language_operation(
            before, after, "foreign", "update", body=body, position=1
        ))


if __name__ == "__main__":
    unittest.main()
