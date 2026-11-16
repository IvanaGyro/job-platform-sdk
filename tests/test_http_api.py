"""HTTP route tests with synthetic data and an injected fake client."""
import asyncio
import unittest

try:
    from httpx import ASGITransport, AsyncClient
    from job_platforms.http_api import create_app
except ImportError:
    ASGITransport = None

from job_platforms.providers.tw104.auth import AuthConfig

TOKEN = "test-only-40-characters-long-0123456789ABCDEF"


class FakeClient:
    def __init__(self):
        self.creates = 0

    async def list_resumes(self):
        return [{"versionNo": "test-1"}]

    async def get_resume(self, version):
        return {"resume": {"vno": version}}

    async def get_schema(self, version):
        return {"bio": {"type": "object"}}

    async def create_resume(self):
        self.creates += 1
        return {"versionNo": "created-test-1"}


@unittest.skipIf(ASGITransport is None, "Optional HTTP test dependencies unavailable")
class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(AuthConfig("unused", "unused"), api_token=TOKEN)
        self.fake = FakeClient()
        self.app.state.client = self.fake
        self.app.state.action_lock = asyncio.Lock()
        self.app.state.idempotency_results = {}
        self.http = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test.local"
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)

    def bearer(self, **other):
        return {"Authorization": f"Bearer {TOKEN}", **other}

    async def test_authentication(self):
        missing = await self.http.get("/v1/tw104/resumes")
        bad = await self.http.get("/v1/tw104/resumes",
                                  headers={"Authorization": "Bearer wrong"})
        good = await self.http.get("/v1/tw104/resumes",
                                   headers=self.bearer())
        self.assertEqual((missing.status_code, bad.status_code,
                          good.status_code), (401, 401, 200))

    async def test_provider_capabilities(self):
        response = await self.http.get("/v1/providers",
                                       headers=self.bearer())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["tw104"]["list_resumes"])
        self.assertFalse(response.json()["cake"]["implemented"])

    async def test_get_and_schema(self):
        read = await self.http.get("/v1/tw104/resumes/test-1",
                                   headers=self.bearer())
        schema = await self.http.get(
            "/v1/tw104/resumes/test-1/schema", headers=self.bearer()
        )
        self.assertEqual((read.status_code, schema.status_code), (200, 200))

    async def test_save_is_explicitly_unimplemented(self):
        response = await self.http.patch(
            "/v1/tw104/resumes/test-1", headers=self.bearer(), json=[]
        )
        self.assertEqual(response.status_code, 501)

    async def test_create_idempotency_within_single_process(self):
        missing = await self.http.post("/v1/tw104/resumes",
                                       headers=self.bearer())
        self.assertEqual(missing.status_code, 400)
        headers = self.bearer(**{"Idempotency-Key": "synthetic-key-000001"})
        first = await self.http.post("/v1/tw104/resumes", headers=headers)
        second = await self.http.post("/v1/tw104/resumes", headers=headers)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(self.fake.creates, 1)

    async def test_ambiguous_create_never_repeats_same_key(self):
        from job_platforms.core.errors import VerificationError

        async def uncertain():
            self.fake.creates += 1
            raise VerificationError("Synthetic unknown outcome")

        self.fake.create_resume = uncertain
        headers = self.bearer(**{"Idempotency-Key": "uncertain-create-key-0001"})
        first = await self.http.post("/v1/tw104/resumes", headers=headers)
        repeat = await self.http.post("/v1/tw104/resumes", headers=headers)
        self.assertEqual((first.status_code, repeat.status_code), (409, 409))
        self.assertEqual(self.fake.creates, 1)

    async def test_plan_validation_is_client_error(self):
        async def invalid_plan(version, operations):
            raise ValueError("Synthetic invalid pointer")
        self.fake.plan_edit = invalid_plan
        response = await self.http.post(
            "/v1/tw104/resumes/test-1/plan",
            headers=self.bearer(), json=[{"op": "remove", "path": "/bad"}],
        )
        self.assertEqual(response.status_code, 422)

    async def test_reads_wait_for_create_navigation(self):
        entering = asyncio.Event()
        release = asyncio.Event()

        async def slow_create():
            self.fake.creates += 1
            entering.set()
            await release.wait()
            return {"versionNo": "created"}
        self.fake.create_resume = slow_create
        headers = self.bearer(**{"Idempotency-Key": "locked-create-key-0001"})
        create_task = asyncio.create_task(
            self.http.post("/v1/tw104/resumes", headers=headers)
        )
        try:
            await asyncio.wait_for(entering.wait(), timeout=1)
            read_task = asyncio.create_task(
                self.http.get("/v1/tw104/resumes", headers=self.bearer())
            )
            await asyncio.sleep(0.02)
            self.assertFalse(read_task.done(), "Read bypassed navigation lock")
        finally:
            release.set()
        created, read = await asyncio.gather(create_task, read_task)
        self.assertEqual((created.status_code, read.status_code), (200, 200))

    async def test_other_provider_is_not_falsely_implemented(self):
        response = await self.http.get("/v1/cake/resumes",
                                       headers=self.bearer())
        self.assertEqual(response.status_code, 501)
