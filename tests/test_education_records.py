"""Synthetic, private-data-free tests for the native 104 EDUCATION contract."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.education_records import (
    education_list, education_wire_record, education_operation_body,
    verify_education_operation, ABROAD_REGION,
)

ROW = {
    "schoolId": 123,
    "name": "Synthetic University",
    "departments": [{"name": "Computer Science",
                     "type": [{"no": 456, "des": "Synthetic category"}]}],
    "highest": {"text": "Masters", "value": 9},
    "duration": {
        "startYear": "2023", "startMonth": {"text": 9, "value": 9},
        "endYear": "2025", "endMonth": {"text": 6, "value": 6},
    },
    "status": {"text": "Studying", "value": 3},
    "inSchoolStatus": {"text": "Current", "value": 1},
    "region": {"text": "Taiwan", "value": 1},
    "foreign": [],
    "sort": 1,
}
BASE = {
    "resume": {"vno": "synthetic"},
    "resumeTimestamp": 100,
    "education": {"formData": {
        "themeChoose": {"selectedTheme": {"text": "List", "value": 1}},
        "educations": [deepcopy(ROW)],
    }},
}


class Transport:
    def __init__(self, owner):
        self.owner = owner
        self.calls = []
        self.ambiguous = False

    async def request(self, method, path, *, params, json_data):
        self.calls.append((method, path, deepcopy(json_data), deepcopy(params)))
        assert path == "/profile/ajax/resumeByBlock/education"
        assert params == {"vno": "synthetic"}
        data = json_data["blockValueList"]["education"]
        records = self.owner.doc["education"]["formData"]["educations"]
        if method == "POST":
            posted = data["educations"][0]
            assert "sort" not in posted
            row = deepcopy(ROW)
            row["name"] = posted["name"]
            row["sort"] = len(records) + 1
            records.append(row)
        elif method == "PUT":
            posted = data["educations"][0]
            records[posted["sort"] - 1]["name"] = posted["name"]
        elif method == "DELETE":
            (position,) = data["educations"]["sort"]
            records.pop(position - 1)
            for i, row in enumerate(records, 1):
                row["sort"] = i
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("simulated lost upstream response")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, ambiguous=False):
        self.doc = deepcopy(BASE)
        self._write_lock = asyncio.Lock()
        self.transport = Transport(self)
        self.transport.ambiguous = ambiguous

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class EducationTests(unittest.IsolatedAsyncioTestCase):
    def test_serializer_matches_upstream_selector_rules(self):
        doc = deepcopy(BASE)
        post = education_wire_record(doc["education"]["formData"]["educations"][0])
        self.assertEqual(post["schoolId"], 123)
        self.assertEqual(post["highest"], 9)
        self.assertEqual(post["departments"], [
            {"name": "Computer Science", "type": [456]}
        ])
        self.assertEqual(post["duration"], {
            "startYear": "2023", "startMonth": 9,
            "endYear": "2025", "endMonth": 6,
        })
        self.assertEqual(post["status"], 3)
        self.assertEqual(post["inSchoolStatus"], 1)
        self.assertEqual(post["foreign"], [])
        self.assertEqual(doc, BASE)

    def test_real_104_created_domestic_school_region_is_empty_selector(self):
        # Recorded 104 behavior (synthetic reconstruction, no personal data):
        # POST can persist a school while GET gives region={} and schoolId=0.
        # Neither value is serialized directly into the outgoing region.
        before = deepcopy(BASE)
        requested = deepcopy(ROW)
        requested["name"] = "One new synthetic domestic school"
        requested["schoolId"] = ""
        changes = {k: v for k, v in requested.items() if k != "sort"}
        body = education_operation_body(before, "create", changes=changes)
        after = deepcopy(before)
        observed = deepcopy(requested)
        observed["region"] = {}
        observed["schoolId"] = 0
        observed["sort"] = 2
        after["education"]["formData"]["educations"].append(observed)
        after["resumeTimestamp"] += 1
        self.assertEqual(len(education_list(after)), 2)
        self.assertEqual(education_wire_record(observed)["foreign"], [])
        self.assertEqual(education_wire_record(observed)["schoolId"], "")
        self.assertTrue(verify_education_operation(
            before, after, "create", body=body, position=None
        ))
        # Once accepted as a native GET record, it can also be deleted by
        # the SDK rather than requiring a private raw-HTTP recovery script.
        self.assertEqual(
            education_operation_body(after, "delete", position=2),
            {"blockValueList": {"education": {"educations": {"sort": [2]}}}},
        )

    def test_creation_cannot_silently_change_education_theme(self):
        before = deepcopy(BASE)
        candidate = deepcopy(ROW)
        candidate["schoolId"] = ""
        candidate["name"] = "Another synthetic school"
        body = education_operation_body(
            before, "create",
            changes={k: v for k, v in candidate.items() if k != "sort"},
        )
        after = deepcopy(before)
        observed = deepcopy(candidate)
        observed["sort"] = 2
        observed["region"] = {}
        after["education"]["formData"]["educations"].append(observed)
        after["education"]["formData"]["themeChoose"]["selectedTheme"]["value"] = 2
        self.assertFalse(verify_education_operation(
            before, after, "create", body=body, position=None
        ))
        after = deepcopy(before)
        after["education"]["formData"]["educations"].append(observed)
        after["education"]["formData"]["unexpectedMetadata"] = "synthetic"
        self.assertFalse(verify_education_operation(
            before, after, "create", body=body, position=None
        ))

    def test_empty_domestic_region_does_not_hide_foreign_or_unknown_values(self):
        for invalid_region, foreign in (
            ({}, [{"no": 7001053000}]),
            (None, []),
            ("", []),
            ([], []),
        ):
            with self.subTest(region=type(invalid_region).__name__,
                              foreign=bool(foreign)):
                doc = deepcopy(BASE)
                doc["education"]["formData"]["educations"][0]["region"] = invalid_region
                doc["education"]["formData"]["educations"][0]["foreign"] = foreign
                with self.assertRaises(UnsupportedWrite):
                    education_list(doc)

    def test_general_school_and_foreign_region_branches(self):
        row = deepcopy(ROW)
        row["highest"]["value"] = 11
        row["region"]["value"] = ABROAD_REGION
        row["status"]["value"] = 1
        result = education_wire_record(row)
        self.assertEqual(result["departments"], [
            {"name": "Computer Science", "type": []}
        ])
        self.assertEqual(result["foreign"], [ABROAD_REGION])
        self.assertEqual(result["inSchoolStatus"], "")

    def test_reject_incomplete_native_shape(self):
        for field, value in (
            ("departments", []), ("duration", "not-a-dict"),
            ("highest", 9), ("schoolId", {"id": 1}),
            ("foreign", "unknown"), ("unexpected", 1),
        ):
            with self.subTest(field=field):
                row = deepcopy(ROW)
                row[field] = value
                doc = deepcopy(BASE)
                doc["education"]["formData"]["educations"][0] = row
                with self.assertRaises(UnsupportedWrite):
                    education_list(doc)

    def test_create_update_delete_bodies(self):
        doc = deepcopy(BASE)
        changes = {k: deepcopy(v) for k, v in ROW.items() if k != "sort"}
        changes["name"] = "Second synthetic university"
        created = education_operation_body(doc, "create", changes=changes)
        submitted = created["blockValueList"]["education"]["educations"][0]
        self.assertEqual(submitted["name"], "Second synthetic university")
        self.assertNotIn("sort", submitted)
        self.assertEqual(
            created["blockValueList"]["education"]["themeChoose"],
            {"selectedTheme": 1},
        )
        updated = education_operation_body(
            doc, "update", changes={"name": "Renamed synthetic"}, position=1
        )
        self.assertEqual(
            updated["blockValueList"]["education"]["educations"][0]["sort"], 1
        )
        self.assertEqual(
            education_operation_body(doc, "delete", position=1),
            {"blockValueList": {"education": {"educations": {"sort": [1]}}}},
        )

    async def test_create_readback(self):
        client = Client()
        changes = {k: deepcopy(v) for k, v in ROW.items() if k != "sort"}
        changes["name"] = "New synthetic school"
        result = await client.mutate_education(
            "synthetic", "create", expected_timestamp=100, changes=changes
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["position"], 2)
        self.assertEqual(client.transport.calls[0][0], "POST")
        self.assertEqual(len(client.doc["education"]["formData"]["educations"]), 2)

    async def test_update_and_delete(self):
        client = Client()
        update = await client.mutate_education(
            "synthetic", "update", position=1,
            changes={"name": "Renamed synthetic school"}, expected_timestamp=100,
        )
        self.assertTrue(update["verified"])
        self.assertEqual(client.transport.calls[0][0], "PUT")
        latest = client.doc["resumeTimestamp"]
        delete = await client.mutate_education(
            "synthetic", "delete", position=1, expected_timestamp=latest,
        )
        self.assertTrue(delete["verified"])
        self.assertEqual(client.transport.calls[1][0], "DELETE")
        self.assertEqual(client.doc["education"]["formData"]["educations"], [])

    async def test_stale_and_unsafe_inputs_never_mutate(self):
        for action, changes, position in (
            ("create", {"name": "Missing other fields"}, None),
            ("update", {"sort": 9}, 1),
            ("update", {"name": ""}, 1),
            ("delete", {"name": "invalid"}, 1),
            ("delete", None, 5),
        ):
            with self.subTest(action=action, changes=changes):
                client = Client()
                with self.assertRaises(UnsupportedWrite):
                    await client.mutate_education(
                        "synthetic", action, changes=changes, position=position,
                        expected_timestamp=100,
                    )
                self.assertEqual(client.transport.calls, [])
        client = Client()
        with self.assertRaises(ConflictError):
            await client.mutate_education(
                "synthetic", "delete", position=1, expected_timestamp=99,
            )
        self.assertEqual(client.transport.calls, [])

    async def test_lost_response_does_not_retry(self):
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.mutate_education(
                "synthetic", "update", position=1,
                changes={"name": "Changed"},
                expected_timestamp=100,
            )
        self.assertEqual(len(client.transport.calls), 1)

    def test_concurrent_sibling_edit_invalidates_readback(self):
        original = deepcopy(BASE)
        after = deepcopy(original)
        after["education"]["formData"]["educations"][0]["name"] = "Changed externally"
        body = education_operation_body(
            original, "create", changes={
                **{k: deepcopy(v) for k,v in ROW.items() if k!="sort"},
                "name": "Added"
            }
        )
        after["education"]["formData"]["educations"].append(
            {**deepcopy(ROW), "sort": 2, "name": "Added"}
        )
        self.assertFalse(verify_education_operation(
            original, after, "create", body=body, position=None
        ))

if __name__ == "__main__":
    unittest.main()
