"""Read-only conversion status source mapping and bearer-protected API."""
import argparse
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
import io,json
import unittest
from unittest.mock import patch

from httpx import ASGITransport,AsyncClient
from job_platforms.cli import _parser,_run
from job_platforms.core.errors import UnsupportedWrite,VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.portfolio_preview import (
    conversion_file_id,convert_status_summary,
)
from test_portfolio_records import POPULATED

TOKEN="synthetic-portfolio-preview-token-123456789"
class FakeTransport:
    def __init__(self):
        self.calls=[]
    async def get_json(self,path,*,params):
        self.calls.append((path,params))
        assert path=="/api/resumes/files/convert-status"
        return {"data":{"convertStatus":"success",
                        "urls":["https://example.invalid/signed-preview"]}}
class Client(Resume104Client):
    def __init__(self,page=None):
        self.doc=deepcopy(POPULATED)
        self.transport=FakeTransport()
    async def get_resume(self,vno):
        assert vno=="synthetic"
        return deepcopy(self.doc)
class Browser:
    page=object()
    async def __aenter__(self):return self
    async def __aexit__(self,*_):return False

class ConversionTests(unittest.IsolatedAsyncioTestCase):
    def test_source_path_and_projection(self):
        fid=conversion_file_id(POPULATED,position=1)
        self.assertEqual(fid,"synthetic-not-real")
        out=convert_status_summary({"data":{
            "convertStatus":"success",
            "urls":["https://example.invalid/a","https://example.invalid/b"],
        }})
        self.assertTrue(out["preview_ready"])
        self.assertEqual(out["preview_url_count"],2)
        self.assertNotIn("urls",out)
        with self.assertRaises(UnsupportedWrite):
            conversion_file_id(POPULATED,position=99)
        with self.assertRaises(VerificationError):
            convert_status_summary({"data":{"convertStatus":"success","urls":123}})

    async def test_client_only_get_not_mutate(self):
        c=Client()
        out=await c.get_portfolio_conversion_status(
            "synthetic",position=2,
        )
        self.assertTrue(out["read_only"])
        self.assertTrue(out["preview_ready"])
        self.assertFalse(out["conversion_requested"])
        self.assertEqual(c.transport.calls[0][0],"/api/resumes/files/convert-status")
        self.assertEqual(c.transport.calls[0][1]["tag"],"undefined")
        self.assertEqual(c.transport.calls[0][1]["fileId"],"synthetic-not-real")
        for tag in ("", "../bad", "a&b"):
            with self.assertRaises(UnsupportedWrite):
                await c.get_portfolio_conversion_status("synthetic",position=1,tag=tag)

    async def test_http_bearer_and_cli(self):
        app=create_app(AuthConfig("unused","unused"),api_token=TOKEN,
                       allow_experimental_writes=False)
        app.state.client=Client()
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        path="/v1/tw104/resumes/synthetic/portfolios/1/conversion"
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://localhost",
        ) as http:
            bad=await http.get(path)
            result=await http.get(path,headers={"Authorization":"Bearer "+TOKEN})
        self.assertEqual((bad.status_code,result.status_code),(401,200))
        self.assertTrue(result.json()["preview_ready"])
        with patch("job_platforms.cli.AuthConfig.from_env",
                   return_value=argparse.Namespace(headless=False)),\
             patch("job_platforms.cli.FreshBrowserSession",return_value=Browser()),\
             patch("job_platforms.cli.Resume104Client",Client):
            args=_parser().parse_args([
                "portfolio-conversion","synthetic","--position","1",
            ])
            with redirect_stdout(io.StringIO()) as buf:
                await _run(args)
            self.assertEqual(json.loads(buf.getvalue())["preview_url_count"],1)

if __name__=="__main__":
    unittest.main()
