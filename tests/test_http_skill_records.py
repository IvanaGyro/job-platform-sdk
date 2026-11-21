"""Synthetic 104-only SKILL HTTP CRUD tests. No network or private data."""
import asyncio
import unittest
from httpx import ASGITransport, AsyncClient
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from test_skill_records import Client

TOKEN = "synthetic-test-token-0123456789-abcdef"
PATH = "/v1/tw104/resumes/synthetic/skills"
NEW = {"name": "Rust", "desc": "Synthetic", "tag": []}

class SkillHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(AuthConfig("unused","unused"),api_token=TOKEN,
                              allow_experimental_writes=True)
        self.fake = Client()
        self.app.state.client = self.fake
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(transport=ASGITransport(app=self.app),
                                base_url="http://test.local")
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None,None,None)

    def headers(self, key="synthetic-skill-key-012345", match="123"):
        return {"Authorization":"Bearer "+TOKEN, "If-Match":match,
                "Idempotency-Key":key}

    async def test_create_replay_conflict(self):
        h=self.headers()
        first=await self.http.post(PATH,headers=h,json=NEW)
        replay=await self.http.post(PATH,headers=h,json=NEW)
        changed=await self.http.post(PATH,headers=h,json={**NEW,"name":"Other"})
        self.assertEqual((first.status_code,replay.status_code,changed.status_code),
                         (200,200,409))
        self.assertEqual(first.json()["position"],3)
        self.assertEqual(len(self.fake.transport.calls),1)

    async def test_update_then_delete(self):
        put=await self.http.put(PATH+"/1",json={"desc":"Updated"},
                                headers=self.headers(key="synthetic-put-key-012345"))
        self.assertEqual(put.status_code,200)
        self.assertEqual(self.fake.transport.calls[0][0],"PUT")
        delete=await self.http.delete(PATH+"/2",
            headers=self.headers(key="synthetic-del-key-012345",
                                 match=str(self.fake.doc["resumeTimestamp"])))
        self.assertEqual(delete.status_code,200)
        self.assertEqual(self.fake.transport.calls[1][0],"DELETE")

    async def test_authorization_and_preconditions(self):
        self.assertEqual((await self.http.post(PATH,json=NEW)).status_code,401)
        bare={"Authorization":"Bearer "+TOKEN}
        self.assertEqual((await self.http.post(PATH,json=NEW,headers=bare)).status_code,428)
        self.assertEqual((await self.http.post(PATH,json=NEW,
            headers={**bare,"If-Match":"123"})).status_code,400)
        self.assertFalse(self.fake.transport.calls)

    async def test_invalid_fields_and_stale_timestamp(self):
        a=await self.http.post(PATH,json=NEW,headers=self.headers(match="122"))
        b=await self.http.post(PATH,
            json={"name":"Synthetic","tag":[{"text":"bad"}]},
            headers=self.headers(key="synthetic-bad-key-012345"))
        c=await self.http.put(PATH+"/99",json={"desc":"X"},
            headers=self.headers(key="synthetic-position-key-012345"))
        self.assertEqual((a.status_code,b.status_code,c.status_code),(412,422,422))
        self.assertFalse(self.fake.transport.calls)

    async def test_ambiguous_request_is_not_resubmitted(self):
        self.fake.transport.ambiguous=True
        h=self.headers(key="synthetic-ambiguous-key-012345")
        first=await self.http.post(PATH,json=NEW,headers=h)
        again=await self.http.post(PATH,json=NEW,headers=h)
        self.assertEqual((first.status_code,again.status_code),(409,409))
        self.assertEqual(len(self.fake.transport.calls),1)
        self.assertNotIn("Rust",str(first.json()))

    async def test_feature_switch_disables_mutations(self):
        app=create_app(AuthConfig("unused","unused"),api_token=TOKEN,
                       allow_experimental_writes=False)
        app.state.client=self.fake
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test.local") as http:
            res=await http.post(PATH,json=NEW,headers=self.headers())
            self.assertEqual(res.status_code,501)
            self.assertFalse(self.fake.transport.calls)

if __name__=="__main__":
    unittest.main()
