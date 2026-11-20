"""104 INFO source adapter: synthetic request bodies and PATCH write safety."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.info_fields import (
    INFO_PATHS, info_request_body, native_info_data,
)
from job_platforms.providers.tw104.writers import (
    changed_sections, checked_write_paths, section_request_body,
    patch_path_catalog,
)

FORM = {
    "info": {
        # Read-only account identity fields intentionally excluded from POST.
        "jobStatus": {"text": "Looking", "value": 1},
        "cellphone": "0000000000", "birthYear": "1990",
        "military": {}, "honoraryDischargeYear": "", "honoraryDischargeMonth": {},
        "city": [{"no": 101, "des": "Synthetic city"}],
        "street": "Synthetic street", "bio": "Synthetic introduction",
        "motto": "Learn and build", "trait": [{"text": "Curious", "value": "1"}],
        "personalLink1Url": "https://example.invalid",
        "personalLink1Type": {"text": "Website", "value": 2},
        "personalLink2Url": "", "personalLink2Type": {},
        "personalLink3Url": "", "personalLink3Type": {},
        "personalImageUrl": "", "personalCover": {},
    },
    "addOn": {
        "tel": "", "telArea": "", "contact": "", "englishName": "Synthetic",
        "subCellphone": "", "driveCert": [{"text": "Car", "value": 1}],
        "trafficTool": [{"text": "Train", "value": 3}],
        "nationality": [], "specialRole": [], "dis1Type": None,
        "dis1Level": None, "dis2Type": None, "dis2Level": None,
        "dis3Type": None, "dis3Level": None, "disManual": {},
        "disTool": [], "disDesc": None,
    },
    "themeChoose": {
        "selectedTheme": {"text": "Classic", "value": 1, "name": "InfoThemeClassic"},
        "backgroundColor": "",
    },
    "summaryDisplay": [
        {"text": "Experience", "value": 1},
        {"text": "Skills", "value": 2},
    ],
}
BASE = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "info": {"formData": deepcopy(FORM)},
}


class Transport:
    def __init__(self, owner, *, verify=True):
        self.owner = owner
        self.verify = verify
        self.calls = []

    async def put_json(self, path, data, *, params):
        assert path == "/profile/ajax/resumeByBlock/info"
        assert params == {"vno": "synthetic"}
        self.calls.append(deepcopy(data))
        if self.verify:
            source = data["blockValueList"]["info"]
            self.owner.doc["info"]["formData"]["info"]["motto"] = source["info"]["motto"]
            self.owner.doc["info"]["formData"]["addOn"]["englishName"] = source["addon"]["englishName"]
            self.owner.doc["resumeTimestamp"] += 1
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, verify=True):
        self.doc = deepcopy(BASE)
        self.transport = Transport(self, verify=verify)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert str(resume_id) == "synthetic"
        return deepcopy(self.doc)


class InfoTests(unittest.IsolatedAsyncioTestCase):
    def test_native_source_payload_and_account_field_exclusion(self):
        document = deepcopy(BASE)
        body = info_request_body(document)["blockValueList"]["info"]
        self.assertEqual(body["info"]["city"], 101)
        self.assertEqual(body["info"]["personalLink1Type"], 2)
        self.assertEqual(body["info"]["personalLink2Type"], "")
        self.assertEqual(body["info"]["trait"], [{"text": "Curious", "value": "0"}])
        self.assertNotIn("cellphone", body["info"])
        self.assertNotIn("jobStatus", body["info"])
        self.assertNotIn("birthYear", body["info"])
        self.assertEqual(body["addon"]["driveCert"], [1])
        self.assertEqual(body["addon"]["trafficTool"], [3])
        self.assertIsNone(body["addon"]["disDesc"])
        self.assertEqual(body["themeChoose"]["selectedTheme"], {"value": 1})
        self.assertEqual(body["summaryDisplay"], [1, 2])
        self.assertNotIn("height", body["addon"])
        self.assertEqual(document, BASE)

    def test_static_patch_catalog_reports_only_supported_paths(self):
        catalog = patch_path_catalog()
        self.assertEqual(catalog["operation"], "replace")
        self.assertFalse(catalog["persisted"])
        self.assertFalse(catalog["atomic"])
        paths = {path for items in catalog["sections"].values() for path in items}
        self.assertEqual(paths, set(INFO_PATHS) | {
            path for path in paths if not path.startswith("/info/")
        })
        self.assertIn("/info/formData/info/motto", paths)
        self.assertIn("/experience/formData/seniority/value", paths)
        self.assertNotIn("/info/formData/info/cellphone", paths)
        self.assertNotIn("/experience/formData/experiences", paths)
        self.assertEqual(Resume104Client.supported_patch_paths(), catalog)
        self.assertNotIn("synthetic", str(catalog).lower())

    def test_patch_whitelist_is_specific_to_resume_fields(self):
        allowed = [
            JsonPatchOperation("replace", "/info/formData/info/motto", "Changed"),
            JsonPatchOperation("replace", "/info/formData/addOn/englishName", "New"),
        ]
        self.assertEqual(
            changed_sections(checked_write_paths(allowed)), ["info"]
        )
        self.assertIn("/info/formData/info/street", INFO_PATHS)
        for path in (
            "/info/formData/info/cellphone", "/info/formData/info/birthYear",
            "/info/formData/themeChoose/backgroundColor",
            "/info/formData/info/personalCover",
        ):
            with self.subTest(path=path), self.assertRaises(UnsupportedWrite):
                checked_write_paths([JsonPatchOperation("replace", path, "x")])

    def test_missing_or_unsafe_info_fails_closed(self):
        for field, bad_value in (
            ("city", []), ("trait", "not-array"),
            ("personalLink1Type", {"text": "Site", "value": None}),
            ("motto", {"not": "text"}),
        ):
            with self.subTest(field=field):
                doc = deepcopy(BASE)
                doc["info"]["formData"]["info"][field] = bad_value
                with self.assertRaises(UnsupportedWrite):
                    info_request_body(doc)
        for field in ("info", "addOn", "summaryDisplay", "themeChoose"):
            with self.subTest(field=field):
                doc = deepcopy(BASE)
                del doc["info"]["formData"][field]
                with self.assertRaises(UnsupportedWrite):
                    native_info_data(doc)
        colored = deepcopy(BASE)
        colored["info"]["formData"]["themeChoose"]["selectedTheme"]["value"] = 4
        with self.assertRaises(UnsupportedWrite):
            info_request_body(colored)

    def test_military_date_and_personal_links_branches(self):
        doc = deepcopy(BASE)
        data = doc["info"]["formData"]["info"]
        data["military"] = {"text": "Discharged", "value": 1}
        data["honoraryDischargeYear"] = "2018"
        data["honoraryDischargeMonth"] = {"text": 5, "value": 5}
        body = info_request_body(doc)["blockValueList"]["info"]["info"]
        self.assertEqual(body["honoraryDischargeYear"], "2018")
        self.assertEqual(body["honoraryDischargeMonth"], 5)
        data["military"] = {"text": "Other", "value": 4}
        body = info_request_body(doc)["blockValueList"]["info"]["info"]
        self.assertEqual(body["honoraryDischargeYear"], "")
        self.assertEqual(body["honoraryDischargeMonth"], "")

    async def test_plan_read_only_test_precondition_is_allowed(self):
        client = Client()
        plan, updated = await client.plan_edit("synthetic", [
            {"op": "test", "path": "/info/formData/info/cellphone",
             "value": "0000000000"},
            {"op": "replace", "path": "/info/formData/info/motto",
             "value": "Different"},
        ])
        self.assertEqual(plan.base_timestamp, 100)
        self.assertEqual(updated["info"]["formData"]["info"]["motto"], "Different")
        self.assertEqual(client.transport.calls, [])

    async def test_no_revision_never_yields_an_edit_plan_or_writes(self):
        client = Client()
        client.doc.pop("resumeTimestamp")
        with self.assertRaises(VerificationError):
            await client.plan_edit("synthetic", [{
                "op": "replace", "path": "/info/formData/info/motto",
                "value": "Not writable",
            }])
        plan = EditPlan("synthetic", None, [
            JsonPatchOperation("replace", "/info/formData/info/motto", "Not writable"),
        ])
        with self.assertRaises(VerificationError):
            await client.save_edit(plan)
        self.assertEqual(client.transport.calls, [])

    async def test_plan_rejects_unmapped_or_malformed_info_before_any_write(self):
        client = Client()
        for path, value in (
            ("/info/formData/info/cellphone", "1234567890"),
            ("/info/formData/info/motto", {"unexpected": "object"}),
            ("/info/formData/info/city", []),
        ):
            with self.subTest(path=path, value=value):
                with self.assertRaises(UnsupportedWrite):
                    await client.plan_edit("synthetic", [{
                        "op": "replace", "path": path, "value": value,
                    }])
                self.assertEqual(client.transport.calls, [])
                self.assertEqual(client.doc, BASE)

    async def test_plan_rejects_otherwise_valid_multi_section_with_unmapped_path(self):
        client = Client()
        with self.assertRaises(UnsupportedWrite):
            await client.plan_edit("synthetic", [
                {"op": "replace", "path": "/info/formData/info/motto",
                 "value": "Safe request"},
                {"op": "replace", "path": "/info/formData/info/cellphone",
                 "value": "1234567890"},
            ])
        self.assertEqual(client.transport.calls, [])
        self.assertEqual(client.doc, BASE)

    async def test_multiple_info_fields_saved_in_one_put(self):
        client = Client()
        plan = EditPlan("synthetic", 100, [
            JsonPatchOperation("replace", "/info/formData/info/motto", "Build things"),
            JsonPatchOperation("replace", "/info/formData/addOn/englishName", "Example"),
        ])
        saved = await client.save_edit(plan)
        self.assertEqual(saved["verified_sections"], ["info"])
        self.assertEqual(len(client.transport.calls), 1)
        posted = client.transport.calls[0]["blockValueList"]["info"]
        self.assertEqual(posted["info"]["motto"], "Build things")
        self.assertEqual(posted["addon"]["englishName"], "Example")
        self.assertEqual(client.doc["info"]["formData"]["info"]["street"], "Synthetic street")

    async def test_stale_plan_and_failed_verification_do_not_repeat(self):
        client = Client()
        plan = EditPlan("synthetic", 99, [
            JsonPatchOperation("replace", "/info/formData/info/motto", "Oops"),
        ])
        with self.assertRaises(ConflictError):
            await client.save_edit(plan)
        self.assertEqual(client.transport.calls, [])
        no_apply = Client(verify=False)
        plan = EditPlan("synthetic", 100, [
            JsonPatchOperation("replace", "/info/formData/info/motto", "Changed"),
        ])
        with self.assertRaises(VerificationError):
            await no_apply.save_edit(plan)
        self.assertEqual(len(no_apply.transport.calls), 1)

    def test_info_serialization_uses_same_section_request(self):
        self.assertEqual(info_request_body(BASE), section_request_body(BASE, "info"))


if __name__ == "__main__":
    unittest.main()
