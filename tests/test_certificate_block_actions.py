"""104 CERTIFICATE first initialization and text-only clear, synthetic only."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.certificate_block_actions import (
    certificate_block_body, verify_certificate_block,
)
from job_platforms.providers.tw104.client import Resume104Client

EMPTY = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "certificate": {"formData": {}, "success": True},
}
POPULATED = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "certificate": {"formData": {
        "certificate": {
            "certifications": [], "certificates": [],
            "others": "Synthetic certification text",
        },
        "themeChoose": {"selectedTheme": {
            "text": "Card", "value": 1, "name": "CertificateThemeCard",
        }},
    }, "success": True},
}
TOKEN = "synthetic-certificate-block-http-token-001"
URL = "/v1/tw104/resumes/synthetic/certificate-block"


class Transport:
    def __init__(self, owner, *, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.ambiguous = ambiguous

    async def request(self, method, path, *, params, json_data):
        assert path == "/profile/ajax/resumeByBlock/certificate"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        data = json_data["blockValueList"]["certificate"]
        if method == "PUT":
            self.owner.doc["certificate"]["formData"] = {
                "certificate": {
                    "certifications": [],
                    "certificates": deepcopy(data["certificates"]),
                    "others": data["others"],
                },
                "themeChoose": {"selectedTheme": {
                    "text": "Card", "value": 1, "name": "CertificateThemeCard",
                }},
            }
        elif method == "DELETE":
            assert data == {"certificates": "", "others": ""}
            self.owner.doc["certificate"]["formData"] = {}
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Synthetic response lost")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, doc=EMPTY, *, ambiguous=False):
        self.doc = deepcopy(doc)
        self.transport = Transport(self, ambiguous=ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, version):
        assert version == "synthetic"
        return deepcopy(self.doc)


class CertificateBlockTests(unittest.IsolatedAsyncioTestCase):
    def test_initialization_uses_native_put_and_clear_uses_distinct_delete(self):
        self.assertEqual(
            certificate_block_body(EMPTY, "initialize", others="Synthetic"),
            {"blockValueList": {"certificate": {
                "certificates": [], "others": "Synthetic",
            }}},
        )
        self.assertEqual(
            certificate_block_body(POPULATED, "clear"),
            {"blockValueList": {"certificate": {
                "certificates": "", "others": "",
            }}},
        )

    def test_clear_never_drops_certification_links(self):
        linked = deepcopy(POPULATED)
        linked["certificate"]["formData"]["certificate"]["certificates"] = [
            {"id": 999, "name": "Synthetic Certification"},
        ]
        with self.assertRaises(UnsupportedWrite):
            certificate_block_body(linked, "clear")

    def test_initialization_and_clear_reject_unsafe_states(self):
        for document, action, text in (
            (EMPTY, "initialize", ""), (EMPTY, "initialize", "x" * 201),
            (POPULATED, "initialize", "Synthetic"),
            (EMPTY, "clear", None), (POPULATED, "clear", "unexpected"),
        ):
            with self.subTest(action=action, text=text), self.assertRaises(UnsupportedWrite):
                certificate_block_body(document, action, others=text)
        with self.assertRaises(UnsupportedWrite):
            certificate_block_body(EMPTY, "unknown", others=None)

    async def test_real_write_emulation_initialize_clear_and_timestamp(self):
        client = Client()
        before = await client.get_resume("synthetic")
        added = await client.mutate_certificate_block(
            "synthetic", "initialize", others="Synthetic",
            expected_timestamp=100,
        )
        self.assertTrue(added["verified"])
        self.assertTrue(verify_certificate_block(
            before, client.doc, "initialize",
            body=certificate_block_body(before, "initialize", others="Synthetic"),
        ))
        with self.assertRaises(ConflictError):
            await client.mutate_certificate_block(
                "synthetic", "clear", expected_timestamp=100,
            )
        cleared = await client.mutate_certificate_block(
            "synthetic", "clear", expected_timestamp=101,
        )
        self.assertTrue(cleared["verified"])
        self.assertEqual(client.doc["certificate"]["formData"], {})
        self.assertEqual(
            [x[0] for x in client.transport.calls], ["PUT", "DELETE"]
        )

    async def test_ambiguous_does_not_retry_upstream(self):
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.mutate_certificate_block(
                "synthetic", "initialize", others="Synthetic",
                expected_timestamp=100,
            )
        self.assertEqual(len(client.transport.calls), 1)

    async def test_http_create_replay_collision_and_clear(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        fake = Client()
        app.state.client = fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        headers = {
            "Authorization": "Bearer " + TOKEN, "If-Match": "100",
            "Idempotency-Key": "synthetic-cert-create-key-001",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.invalid",
        ) as http:
            invalid = await http.post(URL, json={"others": ""},
                                      headers=headers)
            self.assertEqual(invalid.status_code, 422)
            created = await http.post(
                URL, json={"others": "Synthetic"}, headers=headers,
            )
            replay = await http.post(
                URL, json={"others": "Synthetic"}, headers=headers,
            )
            collision = await http.post(
                URL, json={"others": "Other"}, headers=headers,
            )
            self.assertEqual(
                (created.status_code, replay.status_code, collision.status_code),
                (200, 200, 409),
            )
            remove = await http.delete(URL, headers={
                **headers, "If-Match": "101",
                "Idempotency-Key": "synthetic-cert-clear-key-001",
            })
            self.assertEqual(remove.status_code, 200)
        self.assertEqual(len(fake.transport.calls), 2)

    async def test_http_clear_with_linked_certificate_is_unavailable(self):
        linked = deepcopy(POPULATED)
        linked["certificate"]["formData"]["certificate"]["certificates"] = [
            {"id": 999, "name": "Synthetic"},
        ]
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        fake = Client(linked)
        app.state.client = fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.invalid",
        ) as http:
            response = await http.delete(URL, headers={
                "Authorization": "Bearer " + TOKEN, "If-Match": "100",
                "Idempotency-Key": "synthetic-cert-unsafe-key-001",
            })
        self.assertEqual(response.status_code, 422)
        self.assertFalse(fake.transport.calls)


if __name__ == "__main__":
    unittest.main()
