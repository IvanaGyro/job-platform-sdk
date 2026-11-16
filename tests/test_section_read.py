"""Read-only section access tests using synthetic data."""
import asyncio
import unittest

from httpx import ASGITransport,AsyncClient

from job_platforms.core.errors import ResumeNotFound
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.http_api import create_app
from job_platforms.cli import _parser

TOKEN="not-a-real-token-for-tests-12345678"


class Page:
    url="https://pda.104.com.tw/profile"

    async def evaluate(self,script,args):
        return {"status":200,"content_type":"application/json",
                "data":{"data":{"resume":{"vno":"synthetic"},
                                "bio":{"formData":{"bio":{"chi":"example","eng":"example"}}}}},
                "profile_version":"synthetic-test-only"}


class SectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_native_section_returned(self):
        client=Resume104Client(Page())
        bio=await client.get_section("synthetic","bio")
        self.assertEqual(bio["formData"]["bio"]["chi"],"example")

    async def test_unknown_section_rejected(self):
        client=Resume104Client(Page())
        with self.assertRaises(ValueError):
            await client.get_section("synthetic","internalSecret")

    async def test_missing_section(self):
        client=Resume104Client(Page())
        with self.assertRaises(ResumeNotFound):
            await client.get_section("synthetic","certificate")

    async def test_http_section(self):
        class Mock:
            async def get_section(self,version,section):
                return {"formData":{"example":"synthetic"}}
        app=create_app(AuthConfig("unused","unused"),api_token=TOKEN)
        app.state.client=Mock()
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as http:
            header={"Authorization":"Bearer "+TOKEN}
            r=await http.get("/v1/tw104/resumes/synthetic/sections/bio",headers=header)
            self.assertEqual(r.status_code,200)
            r=await http.get("/v1/tw104/resumes/synthetic/sections/unknown",headers=header)
            self.assertEqual(r.status_code,400)
            r=await http.get("/v1/cake/resumes/synthetic/sections/bio",headers=header)
            self.assertEqual(r.status_code,501)

    async def test_cli_section_parser(self):
        args=_parser().parse_args(["--provider","tw104","get-section","synthetic","bio"])
        self.assertEqual((args.command,args.resume_id,args.section),("get-section","synthetic","bio"))


if __name__=="__main__":
    unittest.main()
