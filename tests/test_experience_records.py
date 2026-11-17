"""Private-data-free tests for 104 EXPERIENCE source mapping and CRUD."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.experience_records import (
    experience_operation_body, experience_wire_record,
    experience_list, verify_experience_operation,
)

ROW = {
    "companyName": "Synthetic Corporation", "custNo": "", "invoice": 0, "logo": "",
    "industry": [{"no": 123, "des": "Synthetic industry"}],
    "companyScale": "", "jobName": "Engineer",
    "workArea": [{"no": 101, "des": "Synthetic location"}],
    "jobType": {"text": "Full-time", "value": 1},
    "jobCat": [{"no": 456, "des": "Synthetic category"}],
    "duration": {
        "startYear": "2023", "startMonth": {"text": 1, "value": 1},
        "endYear": "", "endMonth": {},
    },
    "description": "Build synthetic systems",
    "skill": [{"text": "Python", "value": "Python"}],
    "management": [],
    "salary": {
        "monthPay": "100", "yearPay": "200",
        "jobParttimeType": {}, "jobParttimePay": "",
    },
    "companyVisibility": True, "stillWork": True,
    "salaryVisibility": False, "sort": 1,
}
BASE = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "experience": {"formData": {
        "themeChoose": {"selectedTheme": {"text": "List", "value": 1}},
        "seniority": {"text": "Experienced", "value": 3},
        "experiences": [deepcopy(ROW)],
    }},
}


class Transport:
    def __init__(self, owner, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.ambiguous = ambiguous

    async def request(self, method, path, *, params, json_data):
        assert path == "/profile/ajax/resumeByBlock/experience"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        records = self.owner.doc["experience"]["formData"]["experiences"]
        content = json_data["blockValueList"]["experience"]["experiences"]
        if method == "POST":
            new = deepcopy(ROW)
            new["sort"] = len(records) + 1
            new["companyName"] = content[0]["companyName"]
            records.append(new)
        elif method == "PUT":
            records[content[0]["sort"] - 1]["jobName"] = content[0]["jobName"]
        elif method == "DELETE":
            records.pop(content["sort"][0] - 1)
            for i, rec in enumerate(records, 1):
                rec["sort"] = i
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Synthetic lost response")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, ambiguous=False):
        self.doc = deepcopy(BASE)
        self.transport = Transport(self, ambiguous=ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class ExperienceTests(unittest.IsolatedAsyncioTestCase):
    def test_salaried_and_part_time_payloads(self):
        payload = experience_wire_record(ROW)
        self.assertEqual(payload["industry"], 123)
        self.assertEqual(payload["duration"]["endMonth"], "")
        self.assertEqual(payload["salary"], {
            "monthPay": "100", "yearPay": "200",
            "jobParttimeType": "", "jobParttimePay": "",
        })
        part = deepcopy(ROW)
        part["jobType"] = {"text": "Part time", "value": 2}
        part["salary"]["jobParttimeType"] = {"text": "Hourly", "value": 5}
        part["salary"]["jobParttimePay"] = "150"
        pay = experience_wire_record(part)["salary"]
        self.assertEqual(pay, {
            "monthPay": "", "yearPay": "",
            "jobParttimeType": 5, "jobParttimePay": "150",
        })
        self.assertEqual(experience_list(BASE), [ROW])

    def test_observed_mixed_salary_number_and_company_scale_selector(self):
        # Real 104 read-only inspection found mixed str/int salary values.
        row = deepcopy(ROW)
        row["salary"]["monthPay"] = 123
        row["salary"]["yearPay"] = 456
        row["companyScale"] = {"text": "Small", "value": 7}
        encoded = experience_wire_record(row)
        self.assertEqual(encoded["salary"]["monthPay"], 123)
        self.assertEqual(encoded["salary"]["yearPay"], 456)
        self.assertEqual(encoded["companyScale"], 7)
        row["companyScale"] = {}
        self.assertEqual(experience_wire_record(row)["companyScale"], "")

    def test_source_methods_and_no_create_sort(self):
        create = {k: deepcopy(v) for k, v in ROW.items() if k not in ("logo", "sort")}
        create["companyName"] = "New Synthetic Corporation"
        body = experience_operation_body(BASE, "create", changes=create)
        record = body["blockValueList"]["experience"]["experiences"][0]
        self.assertEqual(record["companyName"], "New Synthetic Corporation")
        self.assertNotIn("sort", record)
        self.assertEqual(body["blockValueList"]["experience"]["themeChoose"], {"selectedTheme": 1})
        update = experience_operation_body(
            BASE, "update", position=1, changes={"jobName": "Researcher"}
        )
        self.assertEqual(
            update["blockValueList"]["experience"]["experiences"][0]["sort"], 1
        )
        self.assertEqual(
            experience_operation_body(BASE, "delete", position=1),
            {"blockValueList": {"experience": {"experiences": {"sort": [1]}}}},
        )

    def test_unsafe_values_are_rejected(self):
        for action, fields, position in (
            ("create", {"jobName": "Only one field"}, None),
            ("create", {"sort": 3}, None),
            ("update", {"logo": "external.png"}, 1),
            ("update", {"jobType": {"value": 8, "text": "??"}}, 1),
            ("update", {"duration": {"startYear": "2024"}}, 1),
            ("delete", {"jobName": "Wrong body"}, 1),
            ("delete", None, 22),
        ):
            with self.subTest(action=action, fields=fields):
                with self.assertRaises(UnsupportedWrite):
                    experience_operation_body(
                        BASE, action, changes=fields, position=position
                    )
        broken = deepcopy(BASE)
        broken["experience"]["formData"]["experiences"][0]["sort"] = 0
        with self.assertRaises(UnsupportedWrite):
            experience_list(broken)

    def test_descending_sort_is_identified_by_upstream_sort_not_array_index(self):
        before = deepcopy(BASE)
        first = deepcopy(ROW)
        first["sort"] = 2
        first["jobName"] = "Higher sort first"
        second = deepcopy(ROW)
        second["sort"] = 1
        second["jobName"] = "Lower sort second"
        before["experience"]["formData"]["experiences"] = [first, second]
        self.assertEqual(
            [x["sort"] for x in experience_list(before)], [2, 1]
        )
        updated = experience_operation_body(
            before, "update", position=1, changes={"jobName": "Changed low sort"}
        )
        self.assertEqual(
            updated["blockValueList"]["experience"]["experiences"][0]["jobName"],
            "Changed low sort",
        )
        after = deepcopy(before)
        after["experience"]["formData"]["experiences"][1]["jobName"] = "Changed low sort"
        self.assertTrue(verify_experience_operation(
            before, after, "update", body=updated, position=1
        ))
        after["experience"]["formData"]["experiences"][0]["description"] = "Unrelated edit"
        self.assertFalse(verify_experience_operation(
            before, after, "update", body=updated, position=1
        ))

        created_row = {k: deepcopy(v) for k, v in ROW.items() if k not in ("logo", "sort")}
        created_row["companyName"] = "Newest Synthetic"
        create_body = experience_operation_body(
            before, "create", changes=created_row
        )
        created = deepcopy(before)
        newcomer = {**deepcopy(ROW), **created_row, "sort": 3}
        created["experience"]["formData"]["experiences"].insert(0, newcomer)
        self.assertTrue(verify_experience_operation(
            before, created, "create", body=create_body, position=None
        ))

        delete_body = experience_operation_body(before, "delete", position=1)
        deleted = deepcopy(before)
        deleted["experience"]["formData"]["experiences"] = [
            {**deepcopy(first), "sort": 1}
        ]
        self.assertTrue(verify_experience_operation(
            before, deleted, "delete", body=delete_body, position=1
        ))

    async def test_update_create_delete_and_readback(self):
        client = Client()
        changed = await client.mutate_experience(
            "synthetic", "update", expected_timestamp=100,
            position=1, changes={"jobName": "Researcher"}
        )
        self.assertTrue(changed["verified"])
        self.assertEqual(client.transport.calls[0][0], "PUT")
        create = {k: deepcopy(v) for k, v in ROW.items() if k not in ("logo", "sort")}
        create["companyName"] = "Second Synthetic Corporation"
        added = await client.mutate_experience(
            "synthetic", "create",
            expected_timestamp=client.doc["resumeTimestamp"], changes=create
        )
        self.assertEqual(added["position"], 2)
        removed = await client.mutate_experience(
            "synthetic", "delete", position=2,
            expected_timestamp=client.doc["resumeTimestamp"]
        )
        self.assertTrue(removed["verified"])
        self.assertEqual([x[0] for x in client.transport.calls], ["PUT", "POST", "DELETE"])

    async def test_stale_and_ambiguous_not_retried(self):
        client = Client()
        with self.assertRaises(ConflictError):
            await client.mutate_experience(
                "synthetic", "delete", position=1, expected_timestamp=99
            )
        self.assertEqual(client.transport.calls, [])
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.mutate_experience(
                "synthetic", "update", position=1,
                changes={"jobName": "Changed"}, expected_timestamp=100
            )
        self.assertEqual(len(client.transport.calls), 1)

    def test_sibling_and_seniority_change_cannot_pass(self):
        after = deepcopy(BASE)
        after["experience"]["formData"]["experiences"].append({
            **deepcopy(ROW), "sort": 2, "companyName": "Second Synthetic"
        })
        body = experience_operation_body(
            BASE, "create", changes={
                **{k: deepcopy(v) for k, v in ROW.items() if k not in ("logo", "sort")},
                "companyName": "Second Synthetic"
            },
        )
        self.assertTrue(verify_experience_operation(
            BASE, after, "create", body=body, position=None
        ))
        after["experience"]["formData"]["seniority"]["value"] = 4
        self.assertFalse(verify_experience_operation(
            BASE, after, "create", body=body, position=None
        ))
        after["experience"]["formData"]["seniority"]["value"] = 3
        after["experience"]["formData"]["experiences"][0]["description"] = "Concurrent"
        self.assertFalse(verify_experience_operation(
            BASE, after, "create", body=body, position=None
        ))


if __name__ == "__main__":
    unittest.main()
