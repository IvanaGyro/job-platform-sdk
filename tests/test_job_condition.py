"""Synthetic contract tests for the 104 job-condition frontend serializer."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.job_condition import (
    native_job_condition, job_condition_request_body,
)
from job_platforms.providers.tw104.writers import checked_write_paths


FORM = {
    "themeChoose": {"selectedTheme": {"text": "Synthetic", "value": 1}},
    "jobCondition": {
        "jobTimeType": [{"text": "Synthetic", "value": 1}],
        "jobWillType": [{"text": "Synthetic", "value": 2}],
        "jobTimePeriod": [{"text": "Synthetic", "value": 3}],
        "otherTimePeriod": "",
        "workShift": True,
        "onBoardDate": {"text": "After offer", "value": 1},
        "onBoardAfterGetOffer": {"text": "Synthetic", "value": 2},
        "customOnBoardDate": {
            "year": "2027", "month": {"value": 4}, "date": {"value": 5}
        },
        "salary": {"text": "Custom", "value": 4},
        "salaryPeriod": {"text": "Monthly", "value": 5},
        "salaryOfHours": "800",
        "salaryOfMonth": {
            "unitOfTenThousand": {"value": 9},
            "unitOfThousand": {"value": 1},
        },
        "salariesOfYear": {"value": 90},
        "preferArea": [{"no": "SYNTHETIC-AREA", "des": "area"}],
        "preferJobTitle": {"text": "Engineer"},
        "preferJobType": [{"no": "SYNTHETIC-CAT"}],
        "preferJobIndustry": [{"no": "SYNTHETIC-INDUSTRY"}],
        "preferJobContent": "<p>synthetic</p>",
        "remoteWork": {"text": "Hybrid", "value": 2},
    },
}
BASE = {
    "resume": {"vno": "synthetic"},
    "resumeTimestamp": 100,
    "jobCondition": {"formData": deepcopy(FORM)},
}


class Transport:
    def __init__(self, owner):
        self.owner = owner
        self.calls = []

    async def put_json(self, path, data, *, params):
        self.calls.append((path, deepcopy(data), params))
        assert path == "/profile/ajax/resumeByBlock/jobCondition"
        # Synthetic server exposes the same view model as an actual read.
        # This is NOT a substitute for live upstream acceptance testing.
        view = self.owner.doc["jobCondition"]["formData"]["jobCondition"]
        view["preferJobContent"] = data["blockValueList"]["jobCondition"][
            "jobCondition"]["preferJobContent"]
        self.owner.doc["resumeTimestamp"] += 1
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self):
        self.doc = deepcopy(BASE)
        self._write_lock = asyncio.Lock()
        self.transport = Transport(self)

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class JobConditionTests(unittest.IsolatedAsyncioTestCase):
    def test_source_mapped_selectors_and_custom_salary(self):
        original = deepcopy(BASE)
        wire = job_condition_request_body(original)
        self.assertEqual(original, BASE, "serializer must never mutate the document")
        block = wire["blockValueList"]["jobCondition"]
        self.assertEqual(block["themeChoose"], {"selectedTheme": 1})
        data = block["jobCondition"]
        self.assertEqual(data["jobTimeType"], [1])
        self.assertEqual(data["jobWillType"], [2])
        self.assertEqual(data["jobTimePeriod"], [3])
        self.assertEqual(data["preferArea"], ["SYNTHETIC-AREA"])
        self.assertEqual(data["preferJobType"], ["SYNTHETIC-CAT"])
        self.assertEqual(data["preferJobIndustry"], ["SYNTHETIC-INDUSTRY"])
        self.assertEqual(data["onBoardAfterGetOffer"], 2)
        self.assertEqual(data["customOnBoardDate"], {
            "year": "", "month": "", "date": ""
        })
        self.assertEqual(data["salary"], 5)
        self.assertEqual(data["salaryPeriod"], 5)
        self.assertEqual(data["salaryOfMonth"], {
            "unitOfTenThousand": 9, "unitOfThousand": 1
        })
        self.assertEqual(data["salariesOfYear"], 90)
        self.assertEqual(data["workShift"], 1)
        self.assertEqual(data["remoteWork"], 2)
        self.assertEqual(data["preferJobTitle"], "Engineer")

    def test_live_native_get_title_can_be_scalar_text(self):
        doc = deepcopy(BASE)
        doc["jobCondition"]["formData"]["jobCondition"]["preferJobTitle"] = (
            "Synthetic native GET title"
        )
        body = job_condition_request_body(doc)
        self.assertEqual(
            body["blockValueList"]["jobCondition"]["jobCondition"][
                "preferJobTitle"
            ], "Synthetic native GET title"
        )

    def test_salary_selection_two_is_not_custom(self):
        doc = deepcopy(BASE)
        value = doc["jobCondition"]["formData"]["jobCondition"]
        value["salary"]["value"] = 2  # accordanceWithCompany, not custom
        outgoing = job_condition_request_body(doc)["blockValueList"]["jobCondition"]["jobCondition"]
        self.assertEqual(outgoing["salary"], 2)
        self.assertEqual(outgoing["salaryOfHours"], "")
        self.assertEqual(outgoing["salariesOfYear"], "")
        self.assertEqual(
            outgoing["salaryOfMonth"],
            {"unitOfTenThousand": "", "unitOfThousand": ""},
        )

    def test_custom_on_board_date_and_non_custom_salary(self):
        doc = deepcopy(BASE)
        v = doc["jobCondition"]["formData"]["jobCondition"]
        v["onBoardDate"]["value"] = "-1"
        v["salary"]["value"] = 1
        v["remoteWork"] = {}
        v["workShift"] = False
        result = job_condition_request_body(doc)["blockValueList"][
            "jobCondition"]["jobCondition"]
        self.assertEqual(result["onBoardAfterGetOffer"], "")
        self.assertEqual(result["customOnBoardDate"], {
            "year": "2027", "month": 4, "date": 5
        })
        self.assertEqual(result["salary"], 1)
        self.assertEqual(result["salaryOfHours"], "")
        self.assertEqual(result["salaryOfMonth"], {
            "unitOfTenThousand": "", "unitOfThousand": ""
        })
        self.assertEqual(result["salariesOfYear"], "")
        self.assertEqual(result["workShift"], 0)
        self.assertEqual(result["remoteWork"], 0)

    def test_unknown_or_missing_fields_are_rejected(self):
        for action in ("missing", "unknown", "not_array", "not_title", "not_text"):
            with self.subTest(action=action):
                doc = deepcopy(BASE)
                f = doc["jobCondition"]["formData"]["jobCondition"]
                if action == "missing":
                    del f["remoteWork"]
                elif action == "unknown":
                    f["futureUnknownField"] = "x"
                elif action == "not_array":
                    f["preferJobType"] = {}
                elif action == "not_title":
                    f["preferJobTitle"] = {"value": "Unexpected"}
                elif action == "not_text":
                    f["preferJobContent"] = {"html": "unexpected"}
                with self.assertRaises(UnsupportedWrite):
                    job_condition_request_body(doc)

    def test_invalid_enum_and_scalar_coercions_are_rejected(self):
        changes = (
            ("onBoardDate", {"value": "not-a-mode"}),
            ("salary", {"value": 999}),
            ("salaryPeriod", {"value": 999}),
            ("workShift", 99),
            ("remoteWork", 5),
            ("onBoardAfterGetOffer", 5),
        )
        for field, value in changes:
            with self.subTest(field=field):
                doc = deepcopy(BASE)
                doc["jobCondition"]["formData"]["jobCondition"][field] = value
                with self.assertRaises(UnsupportedWrite):
                    job_condition_request_body(doc)

    def test_only_native_known_edit_paths_are_enabled(self):
        self.assertEqual(checked_write_paths([
            JsonPatchOperation(
                "replace", "/jobCondition/formData/jobCondition/preferJobTitle/text",
                "Scientist"
            )
        ]), ["/jobCondition/formData/jobCondition/preferJobTitle/text"])
        with self.assertRaises(UnsupportedWrite):
            checked_write_paths([
                JsonPatchOperation(
                    "replace", "/jobCondition/formData/themeChoose/selectedTheme/value",
                    2
                )
            ])

    async def test_job_content_write_readback_and_other_fields_unchanged(self):
        client = Client()
        original = deepcopy(client.doc)
        plan = EditPlan("synthetic", 100, [
            JsonPatchOperation(
                "replace",
                "/jobCondition/formData/jobCondition/preferJobContent",
                "<p>updated synthetic</p>",
            )
        ])
        result = await client.save_edit(plan)
        self.assertTrue(result["verified"])
        self.assertEqual(result["verified_sections"], ["jobCondition"])
        self.assertEqual(
            client.doc["jobCondition"]["formData"]["jobCondition"]["preferJobTitle"],
            original["jobCondition"]["formData"]["jobCondition"]["preferJobTitle"],
        )
        self.assertEqual(len(client.transport.calls), 1)
        self.assertEqual(client.transport.calls[0][0],
                         "/profile/ajax/resumeByBlock/jobCondition")
        self.assertEqual(client.transport.calls[0][2], {"vno": "synthetic"})

    async def test_unmapped_shapes_fail_before_network_write(self):
        client = Client()
        client.doc["jobCondition"]["formData"]["jobCondition"][
            "remoteWork"
        ] = {"unexpected": 4}
        plan = EditPlan("synthetic", 100, [
            JsonPatchOperation(
                "replace",
                "/jobCondition/formData/jobCondition/preferJobContent",
                "<p>modified</p>",
            )
        ])
        with self.assertRaises(UnsupportedWrite):
            await client.save_edit(plan)
        self.assertEqual(client.transport.calls, [])


if __name__ == "__main__":
    unittest.main()
