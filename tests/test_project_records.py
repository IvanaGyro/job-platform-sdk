"""104 PROJECT no-media native CRUD and sorting, synthetic only."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.project_records import (
    project_records, project_operation_body, verify_project_operation,
)
from job_platforms.providers.tw104.record_sort import sort_body, verify_sort

OPTIONS = {"optionsProjectTheme": [
    {"text": "One column", "value": 1}, {"text": "Two", "value": 2},
]}
CHANGES = {
    "name": "Synthetic Project", "duration": {
        "startYear": "2023", "startMonth": 1,
        "endYear": "2024", "endMonth": 12,
    }, "isInProgress": False,
    "introduction": "<p>Test only</p>",
    "url": "https://example.invalid/project",
}
EMPTY = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "project": {"formData": {}},
}
ROW = {**deepcopy(CHANGES), "img": {"type": 0}, "sort": 1, "isInProgress": 0}
SECOND = {
    **deepcopy(ROW), "name": "Second Synthetic", "sort": 2,
    "url": "https://example.invalid/second",
}
POPULATED = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "project": {"formData": {
        "projects": [deepcopy(ROW), deepcopy(SECOND)],
        "themeChoose": {"selectedTheme": {
            "text": "One column", "value": 1, "name": "ProjectTheme1Column"
        }},
    }},
}


class FakeTransport:
    def __init__(self, owner, *, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.ambiguous = ambiguous

    async def get_json(self, path):
        assert path == "/profile/ajax/options"
        return {"data": deepcopy(OPTIONS)}

    async def request(self, method, path, *, params, json_data):
        assert path == "/profile/ajax/resumeByBlock/project"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        data = json_data["blockValueList"]["project"]
        form = self.owner.doc["project"]["formData"]
        if method == "POST":
            if not form:
                form["projects"] = []
                form["themeChoose"] = {"selectedTheme": {
                    "text": "One column", "value": 1, "name": "ProjectTheme1Column"
                }}
            new = data["projects"][0]
            form["projects"].append({
                **{k: deepcopy(new[k]) for k in CHANGES},
                "img": {"type": 0}, "sort": len(form["projects"]) + 1,
            })
        elif method == "PUT":
            record = data["projects"][0]
            for i, old in enumerate(form["projects"]):
                if old["sort"] == record["sort"]:
                    form["projects"][i] = {
                        **{k: deepcopy(record[k]) for k in CHANGES},
                        "img": {"type": 0}, "sort": record["sort"],
                    }
                    break
            else:
                raise AssertionError("Record not found")
        elif method == "DELETE":
            position = data["projects"]["sort"][0]
            form["projects"] = [
                x for x in form["projects"] if x["sort"] != position
            ]
            for i, record in enumerate(form["projects"], 1):
                record["sort"] = i
            if not form["projects"]:
                self.owner.doc["project"]["formData"] = {}
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Simulated timeout after commit")
        return {"data": {}}

    async def put_json(self, path, body, *, params):
        assert path == "/profile/ajax/swapRecordBySort/project"
        self.calls.append(("SORT", deepcopy(body)))
        move = body["blockValueList"]["project"]["projects"]["sort"]
        rows = self.owner.doc["project"]["formData"]["projects"]
        a,b=move["from"]-1,move["to"]-1
        rows[a],rows[b]=rows[b],rows[a]
        for i,row in enumerate(rows,1):row["sort"]=i
        self.owner.doc["resumeTimestamp"]+=1
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, doc=EMPTY, *, ambiguous=False):
        self.doc = deepcopy(doc)
        self.transport = FakeTransport(self, ambiguous=ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, version):
        assert version == "synthetic"
        return deepcopy(self.doc)


class ProjectTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_first_create_contract(self):
        self.assertEqual(project_records(EMPTY), [])
        body = project_operation_body(EMPTY, "create", changes=CHANGES, options=OPTIONS)
        self.assertEqual(body, {"blockValueList": {"project": {
            "projects": [{
                **deepcopy(CHANGES), "isInProgress": 0,
                "file": {"type": 0, "content": ""},
            }],
            "themeChoose": {"selectedTheme": 1},
        }}})
        self.assertNotIn("sort", body["blockValueList"]["project"]["projects"][0])
        self.assertNotIn("img", body["blockValueList"]["project"]["projects"][0])

    def test_update_existing_no_media_and_delete_sort(self):
        update = project_operation_body(
            POPULATED, "update", changes={"name": "Updated Synthetic"},
            position=2,
        )
        wire = update["blockValueList"]["project"]["projects"][0]
        self.assertEqual(wire["sort"], 2)
        self.assertEqual(wire["name"], "Updated Synthetic")
        self.assertEqual(
            project_operation_body(POPULATED, "delete", position=1),
            {"blockValueList": {"project": {"projects": {"sort": [1]}}}},
        )
        self.assertEqual(
            sort_body(POPULATED, "project", 1, 2),
            {"blockValueList": {"project": {
                "projects": {"sort": {"from": 1, "to": 2}}
            }}},
        )

    def test_reject_media_uploads_and_bad_forms(self):
        for bad in (
            {"name": "Too Few"},
            {**CHANGES, "name": "a" * 121},
            {**CHANGES, "introduction": "x" * 4001},
            {**CHANGES, "url": "javascript:alert(1)"},
            {**CHANGES, "url": "https://example.invalid/" + "a" * 200},
            {**CHANGES, "isInProgress": [1, 2]},
            {**CHANGES, "img": {"type": 1}},
            {**CHANGES, "duration": {"startYear": "2024"}},
        ):
            with self.subTest(keys=list(bad)), self.assertRaises(UnsupportedWrite):
                project_operation_body(EMPTY, "create", changes=bad, options=OPTIONS)
        media = deepcopy(POPULATED)
        media["project"]["formData"]["projects"][0]["img"]["type"] = 1
        with self.assertRaises(UnsupportedWrite):
            project_operation_body(
                media, "update", changes={"name": "No media overwrite"},
                position=1,
            )
        with self.assertRaises(UnsupportedWrite):
            project_operation_body(EMPTY, "create", changes=CHANGES)
        with self.assertRaises(UnsupportedWrite):
            project_operation_body(POPULATED, "delete", position=3)
        with self.assertRaises(UnsupportedWrite):
            project_operation_body(POPULATED, "update", position=1, changes={"file": "evil"})

    async def test_create_update_clear_empty_block(self):
        client = Client()
        added = await client.mutate_project(
            "synthetic", "create", changes=CHANGES, expected_timestamp=100,
        )
        self.assertTrue(added["verified"])
        self.assertEqual(added["position"], 1)
        changed = await client.mutate_project(
            "synthetic", "update", position=1,
            changes={"name": "Updated Synthetic"}, expected_timestamp=101,
        )
        self.assertTrue(changed["verified"])
        removed = await client.mutate_project(
            "synthetic", "delete", position=1, expected_timestamp=102,
        )
        self.assertTrue(removed["verified"])
        self.assertEqual(client.doc["project"]["formData"], {})
        self.assertEqual(
            [entry[0] for entry in client.transport.calls], ["POST", "PUT", "DELETE"]
        )

    async def test_stale_or_ambiguous_write_never_retried(self):
        client=Client(doc=POPULATED)
        with self.assertRaises(ConflictError):
            await client.mutate_project(
                "synthetic", "delete", position=1, expected_timestamp=99
            )
        self.assertFalse(client.transport.calls)
        client=Client(doc=POPULATED, ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.mutate_project(
                "synthetic", "update", position=1,
                changes={"name": "New"}, expected_timestamp=100,
            )
        self.assertEqual(len(client.transport.calls), 1)

    async def test_project_sort_one_swap(self):
        client=Client(doc=POPULATED)
        before=await client.get_resume("synthetic")
        result=await client.sort_records(
            "synthetic","project",1,2,expected_timestamp=100,
        )
        self.assertTrue(result["verified"])
        self.assertTrue(verify_sort(
            before, client.doc, "project", 1, 2,
        ))
        self.assertEqual(client.transport.calls[0][0], "SORT")

    def test_verification_rejects_sibling_changes(self):
        doc=deepcopy(POPULATED)
        body=project_operation_body(doc, "delete", position=1)
        after=deepcopy(doc)
        after["project"]["formData"]["projects"]=[{**deepcopy(SECOND),"sort":1}]
        self.assertTrue(verify_project_operation(
            doc, after, "delete", body=body, position=1
        ))
        after["project"]["formData"]["projects"][0]["name"]="unexpected"
        self.assertFalse(verify_project_operation(
            doc, after, "delete", body=body, position=1
        ))


if __name__=="__main__":
    unittest.main()
