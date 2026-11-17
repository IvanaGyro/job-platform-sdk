"""Read-only dynamic custom1..custom6 and under18 104 schema exposure."""
import argparse
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
import io,json
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from job_platforms.cli import _parser,_run
from job_platforms.core.errors import ResumeNotFound,VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104 import AuthConfig,Resume104Client

TOKEN="synthetic-native-custom-slots-token-00001"
DOCUMENT={
    "resume":{"vno":"synthetic"},"resumeTimestamp":101,
    "custom1":{
        "formData":{
            "custom":{
                "name":"Synthetic",
                "sort":1,
                "content":[{"introduction":"<p>Example</p>"}],
            },
            "themeChoose":{"selectedTheme":{"value":3}},
        },
    },
    "custom4":{
        "formData":{
            "custom":{
                "name":"Synthetic another",
                "sort":4,
                "content":[{"file":[{"type":0}]}],
            },
        },
    },
    "under18":{"formData":{"test_only":True}},
}

class Client(Resume104Client):
    def __init__(self,doc=DOCUMENT):
        self.doc=deepcopy(doc)

    async def get_resume(self,resume_id):
        assert resume_id=="synthetic"
        return deepcopy(self.doc)

class CLIClient(Client):
    def __init__(self,_page):
        super().__init__()

class Browser:
    page=object()
    async def __aenter__(self):return self
    async def __aexit__(self,*_):return False

class DynamicCustomReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_dynamic_sections_and_under18_are_readonly(self):
        c=Client()
        self.assertEqual(len(c.CUSTOM_SLOTS),6)
        self.assertIn("custom4",c.SECTIONS)
        self.assertIn("under18",c.SECTIONS)
        read=await c.get_section("synthetic","custom4")
        self.assertEqual(read,DOCUMENT["custom4"])
        schema=await c.get_schema("synthetic")
        self.assertIn("custom1",schema)
        self.assertIn("custom4",schema)
        self.assertIn("under18",schema)
        self.assertNotIn("custom2",schema)

    async def test_custom_slot_summary_is_schema_not_resume_values(self):
        slots=await Client().list_custom_slots("synthetic")
        self.assertEqual([x["section"] for x in slots],["custom1","custom4"])
        self.assertNotIn("Synthetic",str(slots))
        with self.assertRaises(ValueError):
            await Client().get_section("synthetic","custom7")
        with self.assertRaises(ResumeNotFound):
            await Client().get_section("synthetic","custom2")
        self.assertEqual(await Client({"resume":{"vno":"synthetic"}}).list_custom_slots("synthetic"),[])

    async def test_malformed_custom_slot_fails_closed(self):
        malformed=deepcopy(DOCUMENT)
        malformed["custom1"]="unexpected non-object"
        with self.assertRaises(VerificationError):
            await Client(malformed).list_custom_slots("synthetic")

    async def test_http_custom_slots_requires_token(self):
        app=create_app(AuthConfig("unused","unused"),api_token=TOKEN)
        app.state.client=Client()
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://test.invalid",
        ) as http:
            path="/v1/tw104/resumes/synthetic/custom-slots"
            unauth=await http.get(path)
            ok=await http.get(path,headers={"Authorization":"Bearer "+TOKEN})
            self.assertEqual((unauth.status_code,ok.status_code),(401,200))
            self.assertEqual([v["section"] for v in ok.json()],["custom1","custom4"])

    async def test_cli_custom_slots_dispatch(self):
        with patch("job_platforms.cli.AuthConfig.from_env",
                   return_value=argparse.Namespace(headless=False)),\
             patch("job_platforms.cli.FreshBrowserSession",return_value=Browser()),\
             patch("job_platforms.cli.Resume104Client",CLIClient):
            command=_parser().parse_args(["custom-slots","synthetic"])
            with redirect_stdout(io.StringIO()) as captured:
                await _run(command)
        data=json.loads(captured.getvalue())
        self.assertEqual([v["section"] for v in data],["custom1","custom4"])


if __name__=="__main__":
    unittest.main()
