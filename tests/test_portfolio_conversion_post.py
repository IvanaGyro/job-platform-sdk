"""Synthetic-only conversion thumbnail file POST, no real 104 account."""
import asyncio,base64
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError,VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.transport import BrowserTransport,BrowserUpload
from test_portfolio_records import POPULATED

PDF=b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"

class FakePage:
    url="https://pda.104.com.tw/profile"
    def __init__(self):self.calls=[]
    async def evaluate(self,script,args):
        assert "new FormData()" in script
        assert "body.append(arg.file.field_name, file, file.name)" in script
        self.calls.append(args)
        return {
            "status":200,"content_type":"application/json",
            "data":{"data":{"fileId":"synthetic-id","pending":True}},
            "profile_version":"synthetic-next",
        }

class FakeTransport:
    def __init__(self):self.calls=[]
    async def request(self,method,path,*,multipart_fields,multipart_upload):
        assert method=="POST"
        assert path=="/api/resumes/files/convert-preview-thumbnail"
        assert multipart_fields=={}
        assert multipart_upload.field_name=="convertPreviewThumbnail"
        self.calls.append(multipart_upload)
        return type("Response",(),{
            "status":200,
            "data":{"data":{"fileId":"synthetic-file-id","pending":True}},
        })()

class FakeClient(Resume104Client):
    def __init__(self):
        self.transport=FakeTransport()
        self.doc=deepcopy(POPULATED)
        self._write_lock=asyncio.Lock()
    async def get_resume(self,vno):
        assert vno=="synthetic"
        return deepcopy(self.doc)

class ConversionPostTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_multipart_conversion_file_no_text_fields(self):
        page=FakePage()
        transport=BrowserTransport(page)
        transport._profile_version="synthetic-prior"
        response=await transport.request(
            "POST","/api/resumes/files/convert-preview-thumbnail",
            multipart_fields={},
            multipart_upload=BrowserUpload(
                "convertPreviewThumbnail","synthetic.pdf","application/pdf",PDF,
            ),
        )
        self.assertEqual(response.status,200)
        self.assertEqual(len(page.calls),1)
        self.assertEqual(page.calls[0]["multipart"],{})
        self.assertEqual(page.calls[0]["file"]["field_name"],
                         "convertPreviewThumbnail")
        self.assertEqual(base64.b64decode(page.calls[0]["file"]["base64"]),PDF)
        self.assertEqual(transport._profile_version,"synthetic-next")

    async def test_conversion_rejects_incorrect_route_or_extra_text(self):
        page=FakePage()
        transport=BrowserTransport(page)
        transport._profile_version="synthetic-prior"
        upload=BrowserUpload(
            "convertPreviewThumbnail","synthetic.pdf","application/pdf",PDF,
        )
        for path,fields in (
            ("/profile/ajax/resumeByBlock/portfolio",{}),
            ("/api/resumes/files/convert-preview-thumbnail",{"extra":"value"}),
        ):
            with self.subTest(path=path),self.assertRaises(ValueError):
                await transport.request(
                    "POST",path,multipart_fields=fields,multipart_upload=upload,
                )
        self.assertEqual(page.calls,[])

    async def test_sdk_no_blind_retry_and_precondition(self):
        c=FakeClient()
        with self.assertRaises(ConflictError):
            await c.request_portfolio_conversion(
                "synthetic",expected_timestamp=99,
                filename="synthetic.pdf",content_type="application/pdf",
                content=PDF,
            )
        self.assertEqual(c.transport.calls,[])
        result=await c.request_portfolio_conversion(
            "synthetic",expected_timestamp=100,
            filename="synthetic.pdf",content_type="application/pdf",
            content=PDF,
        )
        self.assertTrue(result["submitted"])
        self.assertFalse(result["preview_verified"])
        self.assertFalse(result["created_resume_attachment"])
        self.assertEqual(len(c.transport.calls),1)
        self.assertEqual(result["conversion_response_fields"],["fileId","pending"])

if __name__=="__main__":
    unittest.main()
