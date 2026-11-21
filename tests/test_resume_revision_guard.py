"""All 104 native writers must reject absent or malformed revision GETs.

Only a synthetic resume and a transport that refuses every network request
are used here. The test deliberately supplies no section data: version
preflight must fail before any native encoder or remote write can run.
"""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, VerificationError
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.revision_guard import (
    is_revision, revision_matches, require_revision_match,
)


class NoNetworkTransport:
    def __init__(self):
        self.calls = []

    async def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("Revision preflight must not contact upstream")

    async def put_json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("Revision preflight must not write")

    async def get_json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("Revision preflight must not fetch options")


class MinimalClient(Resume104Client):
    def __init__(self, stamp):
        self.doc = {"resume": {"vno": "synthetic"}}
        if stamp is not MISSING:
            self.doc["resumeTimestamp"] = stamp
        self._write_lock = asyncio.Lock()
        self.transport = NoNetworkTransport()

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


MISSING = object()


class RevisionGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_valid_numeric_and_string_revisions_with_normalized_comparison(self):
        for revision in (0, 1, 123, "0", "123", "2026-11-20T16:25:00+08:00", "v-abcd_1"):
            with self.subTest(revision=revision):
                self.assertTrue(is_revision(revision))
                self.assertTrue(revision_matches({"resumeTimestamp": revision}, revision))
        self.assertTrue(revision_matches({"resumeTimestamp": 123}, "123"))
        self.assertTrue(revision_matches({"resumeTimestamp": "123"}, 123))
        self.assertFalse(revision_matches({"resumeTimestamp": "123"}, "0123"))
        self.assertFalse(revision_matches({"resumeTimestamp": 123}, "123 "))

    def test_missing_sentinel_boolean_and_oversized_revisions_fail_closed(self):
        for bad in (MISSING, None, True, False, 1.0, -1, "", " ",
                    "None", "null", "undefined", "NaN", "TRUE", "False",
                    "123\n", " 123", "1" * 129, 10**128):
            with self.subTest(bad=repr(bad)):
                self.assertFalse(is_revision(bad))
                missing = {} if bad is MISSING else {"resumeTimestamp": bad}
                self.assertFalse(revision_matches(missing, "None"))
                self.assertFalse(revision_matches(missing, 123))
                with self.assertRaises(ConflictError):
                    require_revision_match(missing, 123)
        self.assertFalse(revision_matches({"resumeTimestamp": 123}, None))
        self.assertFalse(revision_matches({"resumeTimestamp": 123}, True))
        self.assertFalse(revision_matches({"resumeTimestamp": 123}, "None"))
        self.assertFalse(revision_matches(None, 123))

    async def test_every_native_writer_aborts_before_its_first_write(self):
        # The native API methods all have a common mandatory revision check.
        # An invalid revision must stop even completely missing section data.
        methods = [
            ("mutate_skill", ("synthetic", "delete"), {"position": 1}),
            ("mutate_education", ("synthetic", "delete"), {"position": 1}),
            ("mutate_experience", ("synthetic", "delete"), {"position": 1}),
            ("mutate_certificate_block", ("synthetic", "clear"), {}),
            ("mutate_bio", ("synthetic", "clear"), {}),
            ("mutate_referrer", ("synthetic", "delete"), {"position": 1}),
            ("mutate_project", ("synthetic", "delete"), {"position": 1}),
            ("mutate_portfolio", ("synthetic", "delete"), {"position": 1}),
            ("mutate_custom_text", ("synthetic", "delete"), {"slot": 1}),
            ("mutate_language", ("synthetic", "foreign", "delete"), {"position": 1}),
            ("set_theme", ("synthetic", "info", 1), {}),
            ("sort_records", ("synthetic", "skill", 1, 2), {}),
            ("request_portfolio_conversion", ("synthetic",), {
                "filename": "synthetic.pdf", "content_type": "application/pdf",
                "content": b"%PDF-1.7\n%%EOF\n",
            }),
        ]
        for stamp, expected in (
            (MISSING, "None"), (None, None), (None, "None"),
            ("null", "null"), (False, False), (100, None),
            (100, True), (100, "undefined"),
        ):
            for name, args, kwargs in methods:
                with self.subTest(method=name, stamp=repr(stamp), expected=repr(expected)):
                    client = MinimalClient(stamp)
                    with self.assertRaises(ConflictError):
                        await getattr(client, name)(
                            *args, expected_timestamp=expected, **kwargs,
                        )
                    self.assertEqual(client.transport.calls, [])

    async def test_json_patch_plan_and_apply_require_real_revision(self):
        operations = [{
            "op": "replace", "path": "/bio/formData/bio/chi",
            "value": "Synthetic only",
        }]
        for stamp in (MISSING, None, True, "None", "null", " "):
            with self.subTest(stamp=repr(stamp)):
                client = MinimalClient(stamp)
                with self.assertRaises(VerificationError):
                    await client.plan_edit("synthetic", operations)
                with self.assertRaises(VerificationError):
                    await client.save_edit(EditPlan(
                        "synthetic", stamp if stamp is not MISSING else None,
                        [JsonPatchOperation.from_dict(operations[0])],
                    ))
                self.assertEqual(client.transport.calls, [])


if __name__ == "__main__":
    unittest.main()
