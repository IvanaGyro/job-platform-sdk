"""Synthetic binary multipart FILE=1 transport, SDK, HTTP and CLI tests."""
import argparse
import asyncio
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from job_platforms.cli import _parser, _run
from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.portfolio_records import (
    portfolio_file_fields, verify_portfolio_file_create,
)
from job_platforms.providers.tw104.transport import (
    BrowserTransport, BrowserUpload, MAX_BROWSER_UPLOAD_BYTES,
)
from test_portfolio_records import POPULATED, EMPTY, OPTIONS

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 18 + b"\xff\xd9"
FIELDS = {"name": "Synthetic upload item", "attachName": "synthetic.pdf"}
API_TOKEN = "synthetic-native-portfolio-binary-http-token-001"


class BrowserPage:
    url = "https://pda.104.com.tw/profile"
    def __init__(self):
        self.args = []
    async def evaluate(self,script,args):
        assert "new FormData()" in script
        assert "new File(" in script and "atob(arg.file.base64)" in script
        assert "body.append(arg.file.field_name, file, file.name)" in script
        assert "104-profile-ver" in script
        self.args.append(args)
        return {
            "status": 200,
            "content_type": "application/json",
            "data": {"data": {}},
            "profile_version": "synthetic-revised",
        }


class FakeTransport:
    def __init__(self,owner,*,lost=False):
        self.owner = owner
        self.calls = []
        self.lost = lost

    async def get_json(self,path):
        assert path == "/profile/ajax/options"
        return {"data":deepcopy(OPTIONS)}

    async def request(
        self,method,path,*,params,multipart_fields,
        multipart_upload,
    ):
        assert method == "POST"
        assert path == "/profile/ajax/resumeByBlock/portfolio"
        assert params == {"vno":"synthetic"}
        assert multipart_fields["blockValueList[portfolio][attachType]"] == "1"
        multipart_upload.validate()
        self.calls.append((method,dict(multipart_fields),multipart_upload.filename))
        form = self.owner.doc["portfolio"]["formData"]
        if not form:
            form["themeChoose"]={"selectedTheme":{
                "text":"List","value":1,"name":"PortfolioThemeList",
            }}
            form["portfolios"]=[]
        form["portfolios"].append({
            "name":multipart_fields["blockValueList[portfolio][name]"],
            "sort":len(form["portfolios"])+1,
            "attachType":{"value":1,"text":"File"},
            "attach":{
                "name":multipart_fields["blockValueList[portfolio][attach][name]"],
                "status":0,"url":"",
                "fileId":"synthetic-uploaded-opaque-file-id",
                "thumbnailFileId":"","src":"","crawler":False,
            },
        })
        self.owner.doc["resumeTimestamp"]+=1
        if self.lost:
            raise VerificationError("synthetic ambiguous upstream upload")
        return {"data":{}}


class FileClient(Resume104Client):
    def __init__(self,doc=POPULATED,*,lost=False):
        self.doc=deepcopy(doc)
        self._write_lock=asyncio.Lock()
        self.transport=FakeTransport(self,lost=lost)

    async def get_resume(self,vno):
        assert vno=="synthetic"
        return deepcopy(self.doc)


class FakeBrowser:
    page = object()
    async def __aenter__(self):return self
    async def __aexit__(self,*_):return False


class CLIClient(FileClient):
    SECTIONS=Resume104Client.SECTIONS
    def __init__(self,_page):
        super().__init__()

    async def upload_portfolio_file(self,vno,**kwargs):
        self.report={
            "resume_id":vno,
            "kwargs":{**kwargs,"content":len(kwargs["content"])},
        }
        return {"verified":True,"bytes":len(kwargs["content"])}


class PortfolioFileTests(unittest.IsolatedAsyncioTestCase):
    def test_portfolio_file_native_fields(self):
        self.assertEqual(
            portfolio_file_fields(POPULATED,FIELDS),{
                "blockValueList[portfolio][themeChoose][selectedTheme]":"1",
                "blockValueList[portfolio][name]":"Synthetic upload item",
                "blockValueList[portfolio][attachType]":"1",
                "blockValueList[portfolio][attach][name]":"synthetic.pdf",
                "blockValueList[portfolio][attach][src]":"",
            },
        )
        self.assertEqual(
            portfolio_file_fields(EMPTY,FIELDS,options=OPTIONS),
            portfolio_file_fields(POPULATED,FIELDS),
        )
        with self.assertRaises(UnsupportedWrite):
            portfolio_file_fields(EMPTY,FIELDS)
        for invalid in (
            {**FIELDS, "src": "nonempty"},
            {**FIELDS, "attachName": ""},
            {**FIELDS, "name": "X"*121},
        ):
            with self.assertRaises(UnsupportedWrite):
                portfolio_file_fields(POPULATED,invalid)

    def test_file_magic_maximum_size_and_extension_guards(self):
        for filename,content_type,content in (
            ("document.pdf","application/pdf",PDF),
            ("image.png","image/png",PNG),
            ("photo.jpg","image/jpeg",JPEG),
        ):
            BrowserUpload("attachment",filename,content_type,content).validate()
        for filename,content_type,content in (
            ("evil.pdf","application/pdf",b"not real pdf data"),
            ("image.png","image/png",b"not png!"),
            ("image.jpg","image/jpeg",b"not jpeg"),
            ("../evil.pdf","application/pdf",PDF),
            ("payload.exe","application/pdf",PDF),
            ("document.pdf","text/plain",PDF),
            ("bad.pdf","application/pdf",b""),
            ("oversize.pdf","application/pdf",b"%PDF-"+b"X"*(MAX_BROWSER_UPLOAD_BYTES+1)+b"%%EOF"),
        ):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                BrowserUpload("attachment",filename,content_type,content).validate()
        with self.assertRaises(ValueError):
            BrowserUpload("binary","document.pdf","application/pdf",PDF).validate()

    async def test_real_browser_formdata_wire_but_synthetic_page(self):
        page=BrowserPage()
        transport=BrowserTransport(page)
        transport._profile_version="synthetic-prior-version"
        result=await transport.request(
            "POST","/profile/ajax/resumeByBlock/portfolio",
            params={"vno":"synthetic"},
            multipart_fields=portfolio_file_fields(POPULATED,FIELDS),
            multipart_upload=BrowserUpload("attachment","synthetic.pdf","application/pdf",PDF),
        )
        self.assertEqual(result.status,200)
        self.assertEqual(transport._profile_version,"synthetic-revised")
        self.assertEqual(len(page.args),1)
        argument=page.args[0]
        self.assertEqual(argument["file"]["field_name"],"attachment")
        self.assertEqual(argument["file"]["filename"],"synthetic.pdf")
        self.assertEqual(argument["file"]["content_type"],"application/pdf")
        self.assertEqual(base64.b64decode(argument["file"]["base64"]),PDF)

    async def test_multipart_binary_requires_form_and_prior_get_header(self):
        page=BrowserPage()
        transport=BrowserTransport(page)
        upload=BrowserUpload("attachment","synthetic.pdf","application/pdf",PDF)
        with self.assertRaises(VerificationError):
            await transport.request(
                "POST","/profile/ajax/resumeByBlock/portfolio",
                multipart_fields=portfolio_file_fields(POPULATED,FIELDS),
                multipart_upload=upload,
            )
        transport._profile_version="synthetic-prior-version"
        for kwargs in (
            {"multipart_upload":upload},
            {"multipart_upload":upload, "json_data":{}},
            {"multipart_fields":{}, "multipart_upload":upload, "form_data":{}},
        ):
            with self.assertRaises(ValueError):
                await transport.request(
                    "POST","/profile/ajax/resumeByBlock/portfolio",
                    **kwargs,
                )
        self.assertEqual(page.args,[])

    async def test_sdk_upload_verified_and_preserves_other_attachments(self):
        client=FileClient()
        before=await client.get_resume("synthetic")
        response=await client.upload_portfolio_file(
            "synthetic",expected_timestamp=100,
            name=FIELDS["name"],attach_name=FIELDS["attachName"],
            filename="synthetic.pdf",content_type="application/pdf",content=PDF,
        )
        self.assertTrue(response["verified"])
        self.assertFalse(response["preview_verified"])
        self.assertEqual(len(client.transport.calls),1)
        self.assertTrue(verify_portfolio_file_create(
            before,client.doc,fields=portfolio_file_fields(before,FIELDS),
        ))
        with self.assertRaises(ConflictError):
            await client.upload_portfolio_file(
                "synthetic",expected_timestamp=100,
                name=FIELDS["name"],attach_name=FIELDS["attachName"],
                filename="synthetic.pdf",content_type="application/pdf",content=PDF,
            )

    async def test_sdk_first_empty_form_upload_and_ambiguous_failure(self):
        created=FileClient(EMPTY)
        result=await created.upload_portfolio_file(
            "synthetic",expected_timestamp=100,
            name=FIELDS["name"],attach_name=FIELDS["attachName"],
            filename="synthetic.pdf",content_type="application/pdf",content=PDF,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(len(created.doc["portfolio"]["formData"]["portfolios"]),1)
        ambiguous=FileClient(lost=True)
        with self.assertRaises(VerificationError):
            await ambiguous.upload_portfolio_file(
                "synthetic",expected_timestamp=100,
                name=FIELDS["name"],attach_name=FIELDS["attachName"],
                filename="synthetic.pdf",content_type="application/pdf",content=PDF,
            )
        self.assertEqual(len(ambiguous.transport.calls),1)

    def test_upload_ack_without_file_handle_not_verified(self):
        before=deepcopy(POPULATED)
        after=deepcopy(POPULATED)
        after["portfolio"]["formData"]["portfolios"].append({
            "name":FIELDS["name"],"sort":3,
            "attachType":{"text":"File","value":1},
            "attach":{
                "name":FIELDS["attachName"],"status":0,
                "url":"","fileId":"","thumbnailFileId":"",
                "src":"","crawler":False,
            },
        })
        self.assertFalse(verify_portfolio_file_create(
            before,after,fields=portfolio_file_fields(before,FIELDS),
        ))

    async def test_http_json_base64_file_replay_and_conflict(self):
        app=create_app(AuthConfig("unused","unused"),api_token=API_TOKEN,
                       allow_experimental_writes=True)
        fake=FileClient()
        app.state.client=fake
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        data={
            "name":FIELDS["name"],"attachName":FIELDS["attachName"],
            "filename":"synthetic.pdf","contentType":"application/pdf",
            "base64":base64.b64encode(PDF).decode("ascii"),
        }
        headers={
            "Authorization":"Bearer "+API_TOKEN,
            "If-Match":"100",
            "Idempotency-Key":"synthetic-portfolio-binary-key-0001",
        }
        path="/v1/tw104/resumes/synthetic/portfolio-files"
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://test.invalid",
        ) as http:
            unauthorized=await http.post(path,json=data)
            first=await http.post(path,json=data,headers=headers)
            replay=await http.post(path,json=data,headers=headers)
            conflict=await http.post(
                path,json={**data,"name":"Other Synthetic"},headers=headers,
            )
            stale=await http.post(
                path,json=data,headers={**headers,
                    "If-Match":"99",
                    "Idempotency-Key":"synthetic-stale-portfolio-file-key",
                },
            )
        self.assertEqual(unauthorized.status_code,401)
        self.assertEqual(
            (first.status_code,replay.status_code,conflict.status_code,stale.status_code),
            (200,200,409,412),
        )
        self.assertEqual(len(fake.transport.calls),1)

    async def test_http_ambiguous_upload_blocks_same_idempotency_key(self):
        app=create_app(AuthConfig("unused","unused"),api_token=API_TOKEN,
                       allow_experimental_writes=True)
        fake=FileClient(lost=True)
        app.state.client=fake
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        data={
            "name":FIELDS["name"],"attachName":FIELDS["attachName"],
            "filename":"synthetic.pdf","contentType":"application/pdf",
            "base64":base64.b64encode(PDF).decode("ascii"),
        }
        headers={
            "Authorization":"Bearer "+API_TOKEN,
            "If-Match":"100",
            "Idempotency-Key":"synthetic-ambiguous-file-key-001",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://test.invalid",
        ) as http:
            one=await http.post(
                "/v1/tw104/resumes/synthetic/portfolio-files",
                json=data,headers=headers,
            )
            two=await http.post(
                "/v1/tw104/resumes/synthetic/portfolio-files",
                json=data,headers=headers,
            )
        self.assertEqual((one.status_code,two.status_code),(409,409))
        self.assertEqual(len(fake.transport.calls),1)

    async def test_http_rejects_binary_when_not_explicitly_enabled(self):
        app=create_app(AuthConfig("unused","unused"),api_token=API_TOKEN,
                       allow_experimental_writes=False)
        app.state.client=FileClient()
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        data={
            "name":FIELDS["name"],"attachName":FIELDS["attachName"],
            "filename":"synthetic.pdf","contentType":"application/pdf",
            "base64":base64.b64encode(PDF).decode("ascii"),
        }
        headers={
            "Authorization":"Bearer "+API_TOKEN,
            "If-Match":"100",
            "Idempotency-Key":"synthetic-optin-disabled-001",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://test.invalid",
        ) as http:
            response=await http.post(
                "/v1/tw104/resumes/synthetic/portfolio-files",
                json=data,headers=headers,
            )
        self.assertEqual(response.status_code,501)
        self.assertFalse(app.state.client.transport.calls)

    async def test_http_rejects_invalid_binary_without_remote_write(self):
        app=create_app(AuthConfig("unused","unused"),api_token=API_TOKEN,
                       allow_experimental_writes=True)
        fake=FileClient()
        app.state.client=fake
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        data={
            "name":FIELDS["name"],"attachName":FIELDS["attachName"],
            "filename":"synthetic.pdf","contentType":"application/pdf",
            "base64":"@@@@",
        }
        headers={
            "Authorization":"Bearer "+API_TOKEN,
            "If-Match":"100",
            "Idempotency-Key":"synthetic-invalid-portfolio-file",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://test.invalid",
        ) as http:
            invalid=await http.post(
                "/v1/tw104/resumes/synthetic/portfolio-files",
                json=data,headers=headers,
            )
        self.assertEqual(invalid.status_code,422)
        self.assertEqual(fake.transport.calls,[])

    async def test_cli_local_file_upload_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"synthetic.pdf"
            file.write_bytes(PDF)
            with patch("job_platforms.cli.AuthConfig.from_env",
                       return_value=argparse.Namespace(headless=False)),\
                 patch("job_platforms.cli.FreshBrowserSession",
                       return_value=FakeBrowser()),\
                 patch("job_platforms.cli.Resume104Client",CLIClient):
                args=_parser().parse_args([
                    "portfolio-file","synthetic",
                    "--file",str(file),"--name",FIELDS["name"],
                    "--if-match","100",
                    "--confirm","experimental-file-upload",
                ])
                with redirect_stdout(io.StringIO()) as output:
                    await _run(args)
                self.assertTrue(json.loads(output.getvalue())["verified"])
                bad=Path(d)/"fake.pdf"
                bad.write_bytes(b"not a PDF")
                with self.assertRaises(ValueError):
                    await _run(_parser().parse_args([
                        "portfolio-file","synthetic",
                        "--file",str(bad),"--name","Invalid",
                        "--if-match","100",
                        "--confirm","experimental-file-upload",
                    ]))


if __name__=="__main__":
    unittest.main()
