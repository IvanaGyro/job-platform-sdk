"""104 BIO initial POST and whole-block DELETE, synthetic-only safety tests."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient
from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.bio_actions import bio_action_body, verify_bio_action
from job_platforms.providers.tw104.client import Resume104Client

BASE = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "bio": {"formData": {}}, "sidebar": [],
}
POPULATED = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "bio": {"formData": {"bio": {"chi": "<p>Synthetic Chinese</p>",
                                   "eng": "<p>Synthetic English</p>"}}},
    "sidebar": [],
}
NEW = {"chi": "<p>新內容</p>", "eng": "<p>New synthetic content</p>"}
TOKEN = "synthetic-bio-native-http-token-00001"
PATH = "/v1/tw104/resumes/synthetic/biography"


class Transport:
    def __init__(self, owner, ambiguous=False, apply=True):
        self.owner = owner
        self.ambiguous = ambiguous
        self.apply = apply
        self.calls = []

    async def request(self, method, path, *, params, json_data):
        assert path == "/profile/ajax/resumeByBlock/bio"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        if self.apply:
            if method == "POST":
                data = json_data["blockValueList"]["bio"]["bio"]
                self.owner.doc["bio"]["formData"] = {"bio": deepcopy(data)}
            elif method == "DELETE":
                assert json_data == {"blockValueList": {
                    "bio": {"chi": "", "eng": ""},
                }}
                self.owner.doc["bio"]["formData"] = {}
            else:
                raise AssertionError(method)
            self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Simulated lost response")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, doc=BASE, *, ambiguous=False, apply=True):
        self.doc = deepcopy(doc)
        self.transport = Transport(self, ambiguous, apply)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, version):
        assert version == "synthetic"
        return deepcopy(self.doc)


class BioActionTests(unittest.IsolatedAsyncioTestCase):
    def test_source_mapped_first_post_and_clear_delete(self):
        self.assertEqual(
            bio_action_body(BASE, "create", changes=NEW),
            {"blockValueList": {"bio": {"bio": NEW}}},
        )
        self.assertEqual(
            bio_action_body(POPULATED, "clear"),
            {"blockValueList": {"bio": {"chi": "", "eng": ""}}},
        )
        self.assertEqual(bio_action_body(BASE, "create", changes=NEW)["blockValueList"]["bio"]["bio"]["eng"], NEW["eng"])

    def test_rejects_unsafe_shapes_and_destruction_of_missing_blocks(self):
        for values in (
            {}, {"chi": "only one"},
            {"chi": 2, "eng": "<p>bad</p>"},
            {"chi": "", "eng": ""},
            {"chi": "text", "eng": "", "extra": "unexpected"},
        ):
            with self.subTest(values=values), self.assertRaises(UnsupportedWrite):
                bio_action_body(BASE, "create", changes=values)
        for document, action, fields in (
            (POPULATED, "create", NEW), (BASE, "clear", None),
            (POPULATED, "clear", NEW), (BASE, "unknown", NEW),
        ):
            with self.subTest(action=action), self.assertRaises(UnsupportedWrite):
                bio_action_body(document, action, changes=fields)

    async def test_first_create_and_whole_clear(self):
        client = Client()
        created = await client.mutate_bio(
            "synthetic", "create", changes=NEW, expected_timestamp=100
        )
        self.assertTrue(created["verified"])
        self.assertEqual(client.transport.calls[0][0], "POST")
        with self.assertRaises(ConflictError):
            await client.mutate_bio(
                "synthetic", "clear", expected_timestamp=100
            )
        cleared = await client.mutate_bio(
            "synthetic", "clear", expected_timestamp=101
        )
        self.assertTrue(cleared["verified"])
        self.assertEqual(client.transport.calls[-1][0], "DELETE")
        self.assertEqual(client.doc["bio"]["formData"], {})

    async def test_ambiguous_and_readback_failures_never_retry(self):
        for ambiguous, apply in ((True, True), (False, False)):
            client = Client(doc=POPULATED, ambiguous=ambiguous, apply=apply)
            with self.subTest(ambiguous=ambiguous), self.assertRaises(VerificationError):
                await client.mutate_bio("synthetic", "clear", expected_timestamp=100)
            self.assertEqual(len(client.transport.calls), 1)

    def test_verifier_rejects_unchanged_site(self):
        self.assertFalse(verify_bio_action(
            BASE, BASE, "create", body=bio_action_body(BASE, "create", changes=NEW)
        ))
        self.assertFalse(verify_bio_action(
            POPULATED, POPULATED, "clear", body=bio_action_body(POPULATED, "clear")
        ))

    async def test_http_first_create_replay_and_delete(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        fake = Client()
        app.state.client = fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        headers = {
            "Authorization": "Bearer " + TOKEN,
            "If-Match": "100",
            "Idempotency-Key": "synthetic-bio-create-action-key",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.invalid"
        ) as http:
            bad = await http.post(PATH, json={"chi": "incomplete"}, headers=headers)
            self.assertEqual(bad.status_code, 422)
            valid = await http.post(PATH, json=NEW, headers=headers)
            replay = await http.post(PATH, json=NEW, headers=headers)
            collision = await http.post(PATH, json={**NEW, "eng": "other"}, headers=headers)
            self.assertEqual(
                (valid.status_code, replay.status_code, collision.status_code),
                (200, 200, 409),
            )
            self.assertEqual(len(fake.transport.calls), 1)
            delete_headers = {
                **headers, "If-Match": "101",
                "Idempotency-Key": "synthetic-bio-delete-action-key",
            }
            removed = await http.delete(PATH, headers=delete_headers)
            self.assertEqual(removed.status_code, 200)
        self.assertEqual(len(fake.transport.calls), 2)

    async def test_default_http_disabled(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=False,
        )
        app.state.client = Client()
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.invalid"
        ) as http:
            result = await http.post(PATH, json=NEW, headers={
                "Authorization": "Bearer " + TOKEN,
                "If-Match": "100",
                "Idempotency-Key": "synthetic-bio-disabled-000001",
            })
        self.assertEqual(result.status_code, 501)


if __name__ == "__main__":
    unittest.main()
