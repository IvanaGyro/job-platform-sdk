"""Synthetic 104 layout/theme PUT mapping and HTTP constraints."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient
from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.layout_theme import (
    allowed_theme_values, native_theme, theme_body, verify_theme_write,
)

TOKEN = "synthetic-theme-test-token-long-enough-001"
PATH = "/v1/tw104/resumes/synthetic/themes/skill"
BASE = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 42,
    "skill": {"formData": {
        "skills": [], "themeChoose": {
            "selectedTheme": {"text": "List", "value": 1, "name": "List"}
        },
    }},
    "education": {"formData": {
        "educations": [], "themeChoose": {
            "selectedTheme": {"text": "List", "value": 1, "name": "List"}
        },
    }},
}
OPTIONS = {
    "optionsSkillTheme": [{"text": "List", "value": 1}, {"text": "Cards", "value": 2}],
    "optionsEducationTheme": [{"text": "List", "value": 1}, {"text": "Cards", "value": 2}],
}


class Transport:
    def __init__(self, client, ambiguous=False):
        self.client = client
        self.calls = []
        self.ambiguous = ambiguous

    async def get_json(self, path):
        assert path == "/profile/ajax/options"
        return {"data": deepcopy(OPTIONS)}

    async def put_json(self, path, body, *, params):
        self.calls.append((path, deepcopy(body), params))
        assert path == "/profile/ajax/resumeByBlock/layout"
        assert params == {"vno": "synthetic"}
        theme = body["blockValueList"]["layout"]["themeChoose"]
        section = theme["block"]
        value = theme["selectedTheme"]
        self.client.doc[section]["formData"]["themeChoose"]["selectedTheme"] = {
            "text": "Cards", "name": "Cards", "value": value,
        }
        self.client.doc["resumeTimestamp"] += 1
        if self.ambiguous:
            raise VerificationError("Lost response")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, ambiguous=False):
        self.doc = deepcopy(BASE)
        self.transport = Transport(self, ambiguous)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class ThemeTests(unittest.IsolatedAsyncioTestCase):
    def test_known_options_and_native_layout_wire(self):
        self.assertEqual(allowed_theme_values(OPTIONS, "skill"), {1, 2})
        self.assertEqual(native_theme(BASE, "skill"), 1)
        self.assertEqual(theme_body(BASE, OPTIONS, "skill", 2), {
            "blockValueList": {"layout": {
                "themeChoose": {"block": "skill", "selectedTheme": 2}
            }}
        })
        for option in (-1, False, 99, "2"):
            with self.subTest(option=option), self.assertRaises(UnsupportedWrite):
                theme_body(BASE, OPTIONS, "skill", option)
        with self.assertRaises(UnsupportedWrite):
            theme_body(BASE, OPTIONS, "bio", 1)
        with self.assertRaises(UnsupportedWrite):
            allowed_theme_values({"optionsSkillTheme": [{"value": 1}, {"value": 1}]}, "skill")

    async def test_theme_change_no_op_and_stale(self):
        client = Client()
        no_op = await client.set_theme("synthetic", "skill", 1, expected_timestamp=42)
        self.assertFalse(no_op["persisted"])
        self.assertEqual(client.transport.calls, [])
        result = await client.set_theme("synthetic", "skill", 2, expected_timestamp=42)
        self.assertEqual(result["selected_theme"], 2)
        self.assertTrue(result["verified"])
        self.assertEqual(len(client.transport.calls), 1)
        with self.assertRaises(ConflictError):
            await client.set_theme("synthetic", "skill", 1, expected_timestamp=42)
        self.assertEqual(len(client.transport.calls), 1)

    async def test_ambiguous_write_not_repeated(self):
        client = Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.set_theme("synthetic", "skill", 2, expected_timestamp=42)
        self.assertEqual(len(client.transport.calls), 1)

    def test_unrelated_field_change_not_verified(self):
        after = deepcopy(BASE)
        after["skill"]["formData"]["themeChoose"]["selectedTheme"]["value"] = 2
        after["skill"]["formData"]["skills"].append({"name": "Unexpected"})
        self.assertFalse(verify_theme_write(BASE, after, "skill", 2))

    async def test_http_request_replay_invalid_and_opt_in(self):
        app = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=True,
        )
        fake = Client()
        app.state.client = fake
        app.state.action_lock = asyncio.Lock()
        app.state.idempotency_results = {}
        headers = {
            "Authorization": "Bearer " + TOKEN, "If-Match": "42",
            "Idempotency-Key": "synthetic-theme-key-00000001",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test.local") as http:
            bad = await http.put(PATH, headers=headers, json={"selectedTheme": 99})
            self.assertEqual(bad.status_code, 422)
            self.assertEqual(fake.transport.calls, [])
            valid = await http.put(PATH, headers=headers, json={"selectedTheme": 2})
            replay = await http.put(PATH, headers=headers, json={"selectedTheme": 2})
            reused = await http.put(PATH, headers=headers, json={"selectedTheme": 1})
            self.assertEqual(
                (valid.status_code, replay.status_code, reused.status_code),
                (200, 200, 409),
            )
            self.assertEqual(len(fake.transport.calls), 1)
        off = create_app(
            AuthConfig("unused", "unused"), api_token=TOKEN,
            allow_experimental_writes=False,
        )
        off.state.client = Client()
        off.state.action_lock = asyncio.Lock()
        off.state.idempotency_results = {}
        async with AsyncClient(transport=ASGITransport(app=off), base_url="http://test.local") as http:
            result = await http.put(PATH, headers=headers, json={"selectedTheme": 2})
            self.assertEqual(result.status_code, 501)


if __name__ == "__main__":
    unittest.main()
