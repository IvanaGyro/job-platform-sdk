"""Mock-only tests for opt-in BIO PATCH; never uses real account data."""
import asyncio
import unittest

from httpx import ASGITransport, AsyncClient

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.core.patch import EditPlan, JsonPatchOperation
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig

TOKEN="only-for-tests-not-a-real-secret-abcdef123"
PATCH_PATH="/v1/tw104/resumes/demo"
BASE_OP=[{"op":"replace","path":"/bio/formData/bio/chi","value":"synthetic"}]


class MockWriter:
    def __init__(self):
        self.write_count=0

    async def plan_edit(self,resume_id,ops):
        return EditPlan(resume_id,123,[JsonPatchOperation.from_dict(x) for x in ops]), {}

    async def save_edit(self,plan):
        if any(op.path.startswith("/info") for op in plan.operations):
            raise UnsupportedWrite("Unsupported test field")
        self.write_count+=1
        return {"persisted":True,"verified":True,"changed_paths":[x.path for x in plan.operations]}


class PatchApiTests(unittest.IsolatedAsyncioTestCase):
    async def create_client(self,enabled):
        app=create_app(AuthConfig("unused","unused"),api_token=TOKEN,
                       allow_experimental_writes=enabled)
        mock=MockWriter()
        app.state.client=mock
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        http=AsyncClient(transport=ASGITransport(app=app),base_url="http://test.local")
        await http.__aenter__()
        return http,mock

    def headers(self,**more):
        return {"Authorization":f"Bearer {TOKEN}",**more}

    async def test_default_patch_is_disabled(self):
        http,mock=await self.create_client(False)
        try:
            r=await http.patch(PATCH_PATH,json=BASE_OP,headers=self.headers())
            self.assertEqual(r.status_code,501)
            self.assertEqual(mock.write_count,0)
        finally:await http.__aexit__(None,None,None)

    async def test_requires_precondition_and_idempotency(self):
        http,mock=await self.create_client(True)
        try:
            r=await http.patch(PATCH_PATH,json=BASE_OP,headers=self.headers())
            self.assertEqual(r.status_code,428)
            r=await http.patch(PATCH_PATH,json=BASE_OP,headers=self.headers(**{"If-Match":"123"}))
            self.assertEqual(r.status_code,400)
            self.assertEqual(mock.write_count,0)
        finally:await http.__aexit__(None,None,None)

    async def test_write_once_and_idempotency_key_conflict(self):
        http,mock=await self.create_client(True)
        try:
            headers=self.headers(**{
                "If-Match":'"123"',
                "Idempotency-Key":"synthetic-key-long-enough"
            })
            first=await http.patch(PATCH_PATH,json=BASE_OP,headers=headers)
            repeat=await http.patch(PATCH_PATH,json=BASE_OP,headers=headers)
            conflict=await http.patch(PATCH_PATH,json=[
                {"op":"replace","path":"/bio/formData/bio/chi","value":"other"}
            ],headers=headers)
            self.assertEqual((first.status_code,repeat.status_code,conflict.status_code),(200,200,409))
            self.assertEqual(mock.write_count,1)
        finally:await http.__aexit__(None,None,None)

    async def test_stale_version_rejected(self):
        http,mock=await self.create_client(True)
        try:
            headers=self.headers(**{"If-Match":"122","Idempotency-Key":"synthetic-stale-version-key"})
            r=await http.patch(PATCH_PATH,json=BASE_OP,headers=headers)
            self.assertEqual(r.status_code,412)
            self.assertEqual(mock.write_count,0)
        finally:await http.__aexit__(None,None,None)

    async def test_other_sections_explicitly_unimplemented(self):
        http,mock=await self.create_client(True)
        try:
            headers=self.headers(**{"If-Match":"123","Idempotency-Key":"synthetic-unsupported-field"})
            r=await http.patch(PATCH_PATH,json=[
                {"op":"replace","path":"/info/formData/info/motto","value":"synthetic"}
            ],headers=headers)
            self.assertEqual(r.status_code,501)
            self.assertEqual(mock.write_count,0)
        finally:await http.__aexit__(None,None,None)


if __name__=="__main__":
    unittest.main()
