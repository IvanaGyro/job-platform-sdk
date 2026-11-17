"""CUSTOM TEXT real-shape SDK via synthetic CLI and localhost HTTP."""
import argparse
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from job_platforms.cli import _parser, _run
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_custom_text_live import Client as CustomClient

TOKEN="synthetic-custom-text-api-token-123456789000"
ROOT="/v1/tw104/resumes/synthetic/custom-text"

class CLIClient(CustomClient):
    def __init__(self,page):
        super().__init__()

class FakeBrowser:
    page=object()
    async def __aenter__(self):return self
    async def __aexit__(self,*_):return False

class CustomTextHttpCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_http_create_update_delete_replay(self):
        app=create_app(
            AuthConfig("unused","unused"),api_token=TOKEN,
            allow_experimental_writes=True,
        )
        c=CustomClient()
        app.state.client=c
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        def headers(ts,key):
            return {
                "Authorization":"Bearer "+TOKEN,"If-Match":str(ts),
                "Idempotency-Key":key,
            }
        data={
            "slot":1,"name":"Synthetic custom",
            "introduction_html":"<p>Synthetic text</p>",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://localhost",
        ) as http:
            noauth=await http.post(ROOT,json=data)
            create=await http.post(ROOT,json=data,
                                   headers=headers(100,"custom-text-create-key-0001"))
            replay=await http.post(ROOT,json=data,
                                   headers=headers(100,"custom-text-create-key-0001"))
            conflict=await http.post(ROOT,json={**data,"name":"Another"},
                                     headers=headers(100,"custom-text-create-key-0001"))
            update=await http.put(
                ROOT+"/1",
                json={"name":"New name"},
                headers=headers(101,"custom-text-update-key-0001"),
            )
            delete=await http.delete(
                ROOT+"/1",headers=headers(102,"custom-text-delete-key-0001"),
            )
        self.assertEqual(noauth.status_code,401)
        self.assertEqual(
            (create.status_code,replay.status_code,conflict.status_code,
             update.status_code,delete.status_code),
            (200,200,409,200,200),
        )
        self.assertNotIn("custom1",c.doc)
        self.assertEqual([x[0] for x in c.transport.calls],[
            "POST","PUT","DELETE",
        ])

    async def test_local_http_rejects_unsafe_and_stale(self):
        app=create_app(
            AuthConfig("unused","unused"),api_token=TOKEN,
            allow_experimental_writes=True,
        )
        c=CustomClient()
        app.state.client=c
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        headers={
            "Authorization":"Bearer "+TOKEN,"If-Match":"100",
            "Idempotency-Key":"custom-text-invalid-key-00001",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://localhost",
        ) as http:
            bad=await http.post(
                ROOT,json={"slot":1,"name":"Synthetic custom",
                           "introduction_html":"<script>bad</script>"},
                headers=headers,
            )
            stale=await http.post(
                ROOT,json={"slot":1,"name":"Synthetic custom",
                           "introduction_html":"<p>Example</p>"},
                headers={**headers,"If-Match":"99",
                         "Idempotency-Key":"custom-text-stale-key-00001"},
            )
            noopt=await http.post(
                ROOT,json={"slot":1,"name":"Synthetic custom",
                           "introduction_html":"<p>Example</p>"},
                headers={**headers,"Idempotency-Key":"custom-text-opt-in-key-00001"},
            )
        self.assertEqual((bad.status_code,stale.status_code,noopt.status_code),
                         (422,412,200))
        self.assertEqual(len(c.transport.calls),1)

    async def test_http_opt_in_required(self):
        app=create_app(
            AuthConfig("unused","unused"),api_token=TOKEN,
            allow_experimental_writes=False,
        )
        app.state.client=CustomClient()
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://localhost",
        ) as http:
            r=await http.post(ROOT,json={
                "slot":1,"name":"Synthetic custom",
                "introduction_html":"<p>Text</p>",
            },headers={
                "Authorization":"Bearer "+TOKEN,
                "If-Match":"100",
                "Idempotency-Key":"custom-text-off-key-0000001",
            })
        self.assertEqual(r.status_code,501)
        self.assertEqual(app.state.client.transport.calls,[])

    async def test_cli_text_crud_with_private_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            html=Path(tmp)/"synthetic-private.html"
            html.write_text("<p>Synthetic text</p>",encoding="utf-8")
            cli=CLIClient(object())
            class ClientFactory:
                SECTIONS=CLIClient.SECTIONS
                def __new__(cls,page):
                    return cli
            with patch("job_platforms.cli.AuthConfig.from_env",
                       return_value=argparse.Namespace(headless=False)),\
                 patch("job_platforms.cli.FreshBrowserSession",
                       return_value=FakeBrowser()),\
                 patch("job_platforms.cli.Resume104Client",
                       ClientFactory):
                async def run(args):
                    parsed=_parser().parse_args(args)
                    with redirect_stdout(io.StringIO()) as capture:
                        await _run(parsed)
                    return json.loads(capture.getvalue())
                made=await run([
                    "custom-text","synthetic","create","--slot","1",
                    "--name","Synthetic custom","--html-file",str(html),
                    "--if-match","100","--confirm","experimental-custom-write",
                ])
                self.assertTrue(made["verified"])
                updated=await run([
                    "custom-text","synthetic","update","--slot","1",
                    "--name","Changed","--if-match","101",
                    "--confirm","experimental-custom-write",
                ])
                self.assertTrue(updated["verified"])
                deleted=await run([
                    "custom-text","synthetic","delete","--slot","1",
                    "--if-match","102","--confirm","experimental-custom-write",
                ])
                self.assertTrue(deleted["verified"])

if __name__=="__main__":
    unittest.main()
