"""Synthetic-only 104 REFERRER CRUD tests, no personal contacts."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.referrer_records import (
    referrer_records, referrer_operation_body, verify_referrer_operation,
)

OPTIONS = {"optionsReferrerTheme": [
    {"text": "List", "value": 1}, {"text": "Card", "value": 2},
]}
FIRST = {
    "name": "Synthetic Reference", "company": "Example Co",
    "position": "Supervisor", "email": "reference@example.invalid",
    "tel": "", "sort": 1,
}
SECOND = {
    "name": "Second Synthetic", "company": "Example University",
    "position": "Mentor", "email": "", "tel": "0000000000", "sort": 2,
}
EMPTY = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "referrer": {"formData": {}},
}
POPULATED = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "referrer": {"formData": {
        "referrers": [deepcopy(FIRST), deepcopy(SECOND)],
        "themeChoose": {"selectedTheme": {
            "text": "List", "value": 1, "name": "ReferrerThemeList"
        }},
    }},
}


class FakeTransport:
    def __init__(self, owner, *, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.options_calls = 0
        self.ambiguous = ambiguous

    async def get_json(self, path):
        assert path == "/profile/ajax/options"
        self.options_calls += 1
        return {"data": deepcopy(OPTIONS)}

    async def request(self, method, path, *, params, json_data):
        assert path == "/profile/ajax/resumeByBlock/referrer"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        content = json_data["blockValueList"]["referrer"]["referrers"]
        form = self.owner.doc["referrer"]["formData"]
        records = form.get("referrers")
        if method == "POST":
            if not form:
                form["referrers"] = []
                form["themeChoose"] = {
                    "selectedTheme": {
                        "text": "List", "value": 1, "name": "ReferrerThemeList"
                    }
                }
                records = form["referrers"]
            rec = {**content[0], "sort": len(records) + 1}
            records.append(rec)
        elif method == "PUT":
            rec = content[0]
            for i, row in enumerate(records):
                if row["sort"] == rec["sort"]:
                    records[i] = deepcopy(rec)
                    break
            else:
                raise AssertionError("sort missing")
        elif method == "DELETE":
            sort = content["sort"][0]
            records[:] = [x for x in records if x["sort"] != sort]
            for i, row in enumerate(records, 1):
                row["sort"] = i
            if not records:
                self.owner.doc["referrer"]["formData"] = {}
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Synthetic response was lost")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, doc=EMPTY, *, ambiguous=False):
        self.doc = deepcopy(doc)
        self.transport = FakeTransport(self, ambiguous=ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, version):
        assert version == "synthetic"
        return deepcopy(self.doc)


class ReferrerTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_source_get_initializes_with_site_first_theme(self):
        self.assertEqual(referrer_records(EMPTY), [])
        create = {k: v for k, v in FIRST.items() if k != "sort"}
        with self.assertRaises(UnsupportedWrite):
            referrer_operation_body(EMPTY, "create", changes=create)
        body = referrer_operation_body(
            EMPTY, "create", changes=create, options=OPTIONS
        )
        self.assertEqual(body, {"blockValueList": {"referrer": {
            "referrers": [create], "themeChoose": {"selectedTheme": 1}
        }}})
        self.assertNotIn("sort", body["blockValueList"]["referrer"]["referrers"][0])

    def test_update_delete_use_native_sort_values(self):
        before = deepcopy(POPULATED)
        before["referrer"]["formData"]["referrers"].reverse()
        self.assertEqual([x["sort"] for x in referrer_records(before)], [2, 1])
        update = referrer_operation_body(
            before, "update", position=1,
            changes={"company": "Renamed Co"},
        )
        wire = update["blockValueList"]["referrer"]["referrers"][0]
        self.assertEqual(wire["sort"], 1)
        self.assertEqual(wire["company"], "Renamed Co")
        after = deepcopy(before)
        after["referrer"]["formData"]["referrers"][1]["company"] = "Renamed Co"
        self.assertTrue(verify_referrer_operation(
            before, after, "update", body=update, position=1
        ))
        after["referrer"]["formData"]["referrers"][0]["name"] = "Concurrent"
        self.assertFalse(verify_referrer_operation(
            before, after, "update", body=update, position=1
        ))
        deleted_body = referrer_operation_body(before, "delete", position=2)
        self.assertEqual(deleted_body, {"blockValueList": {
            "referrer": {"referrers": {"sort": [2]}}
        }})

    def test_validation_requires_contact_and_exact_fields(self):
        for changes in (
            {"name": "Incomplete"},
            {**{k: v for k, v in FIRST.items() if k != "sort"}, "email": "", "tel": ""},
            {**{k: v for k, v in FIRST.items() if k != "sort"}, "sort": 5},
            {**{k: v for k, v in FIRST.items() if k != "sort"}, "company": {"text": "wrong"}},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(UnsupportedWrite):
                    referrer_operation_body(EMPTY, "create", changes=changes, options=OPTIONS)
        with self.assertRaises(UnsupportedWrite):
            referrer_operation_body(POPULATED, "delete", position=9)
        with self.assertRaises(UnsupportedWrite):
            referrer_operation_body(POPULATED, "update", position=1, changes={"foo": "bar"})
        bad = deepcopy(POPULATED)
        bad["referrer"]["formData"]["referrers"][0]["externalId"] = "unknown"
        with self.assertRaises(UnsupportedWrite):
            referrer_records(bad)
        with self.assertRaises(UnsupportedWrite):
            referrer_operation_body(EMPTY, "create", changes={
                k: v for k, v in FIRST.items() if k != "sort"
            }, options={"optionsReferrerTheme": [{"value": False}]})

    def test_live_observed_input_field_maxima(self):
        limits = {"name": 30, "company": 35, "position": 20,
                  "email": 50, "tel": 50}
        template = {k: v for k, v in FIRST.items() if k != "sort"}
        for name, limit in limits.items():
            with self.subTest(name=name):
                valid = dict(template)
                valid[name] = "a" * limit
                referrer_operation_body(
                    EMPTY, "create", changes=valid, options=OPTIONS
                )
                invalid = dict(valid)
                invalid[name] = "a" * (limit + 1)
                with self.assertRaises(UnsupportedWrite):
                    referrer_operation_body(
                        EMPTY, "create", changes=invalid, options=OPTIONS
                    )

    async def test_full_empty_initialization_and_single_delete(self):
        client = Client()
        fields = {k: v for k, v in FIRST.items() if k != "sort"}
        added = await client.mutate_referrer(
            "synthetic", "create", changes=fields, expected_timestamp=100
        )
        self.assertEqual(added["position"], 1)
        self.assertTrue(added["verified"])
        self.assertEqual(client.transport.options_calls, 1)
        changed = await client.mutate_referrer(
            "synthetic", "update", changes={"position": "New Position"},
            position=1, expected_timestamp=101,
        )
        self.assertTrue(changed["verified"])
        removed = await client.mutate_referrer(
            "synthetic", "delete", position=1, expected_timestamp=102,
        )
        self.assertTrue(removed["verified"])
        self.assertEqual(client.doc["referrer"]["formData"], {})
        self.assertEqual([x[0] for x in client.transport.calls], ["POST", "PUT", "DELETE"])

    async def test_stale_and_ambiguous_do_not_send_second_request(self):
        client = Client(doc=POPULATED)
        with self.assertRaises(ConflictError):
            await client.mutate_referrer(
                "synthetic", "delete", position=1, expected_timestamp=99
            )
        self.assertEqual(client.transport.calls, [])
        uncertain = Client(doc=POPULATED, ambiguous=True)
        with self.assertRaises(VerificationError):
            await uncertain.mutate_referrer(
                "synthetic", "update", position=1,
                changes={"name": "Synthetic Changed"}, expected_timestamp=100
            )
        self.assertEqual(len(uncertain.transport.calls), 1)

    def test_create_does_not_overwrite_existing_siblings(self):
        create = {k: v for k, v in FIRST.items() if k != "sort"}
        create["name"] = "Third Synthetic"
        before = deepcopy(POPULATED)
        body = referrer_operation_body(before, "create", changes=create)
        after = deepcopy(before)
        after["referrer"]["formData"]["referrers"].append({
            **create, "sort": 3,
        })
        self.assertTrue(verify_referrer_operation(
            before, after, "create", body=body, position=None
        ))
        after["referrer"]["formData"]["referrers"][0]["email"] = "concurrent@example.invalid"
        self.assertFalse(verify_referrer_operation(
            before, after, "create", body=body, position=None
        ))


if __name__ == "__main__":
    unittest.main()
