"""104 REFERRER two-item special-case sort from official frontend f5d8."""
import asyncio
from copy import deepcopy
import unittest

from httpx import ASGITransport, AsyncClient

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.record_sort import sort_body, verify_sort
from test_referrer_records import POPULATED, EMPTY

TOKEN="synthetic-104-referrer-sort-token-00001"


class FakeTransport:
    def __init__(self, owner, *, lost=False):
        self.owner=owner
        self.lost=lost
        self.calls=[]

    async def put_json(self, path, body, *, params):
        assert path=="/profile/ajax/swapRecordBySort/referrer"
        assert params=={"vno":"synthetic"}
        operation=body["blockValueList"]["referrer"]["referrers"]["sort"]
        assert operation=={"from":2,"to":1}
        self.calls.append(deepcopy(body))
        rows=self.owner.doc["referrer"]["formData"]["referrers"]
        rows[:]=rows[::-1]
        for idx,row in enumerate(rows,1):
            row["sort"]=idx
        self.owner.doc["resumeTimestamp"]+=1
        if self.lost:
            raise VerificationError("Synthetic lost response")
        return {"data":{}}


class FakeClient(Resume104Client):
    def __init__(self,doc=POPULATED,*,lost=False):
        self.doc=deepcopy(doc)
        self.transport=FakeTransport(self,lost=lost)
        self._write_lock=asyncio.Lock()

    async def get_resume(self, version):
        assert version=="synthetic"
        return deepcopy(self.doc)


class ReferrerTwoItemSortTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_frontend_payload_for_both_directions(self):
        # The frontend ignores drag payload and hardcodes 2 -> 1.
        payload={"blockValueList":{"referrer":{"referrers":{"sort":{
            "from":2,"to":1,
        }}}}}
        self.assertEqual(sort_body(POPULATED,"referrer",1,2),payload)
        self.assertEqual(sort_body(POPULATED,"referrer",2,1),payload)
        for a,b in [(1,1),(0,1),(1,3)]:
            with self.assertRaises(UnsupportedWrite):
                sort_body(POPULATED,"referrer",a,b)
        with self.assertRaises(UnsupportedWrite):
            sort_body(EMPTY,"referrer",1,2)
        too_many=deepcopy(POPULATED)
        extra=deepcopy(too_many["referrer"]["formData"]["referrers"][-1])
        extra["sort"]=3
        extra["name"]="Third synthetic contact"
        too_many["referrer"]["formData"]["referrers"].append(extra)
        with self.assertRaises(UnsupportedWrite):
            sort_body(too_many,"referrer",1,2)

    async def test_swap_then_independent_readback(self):
        client=FakeClient()
        original=await client.get_resume("synthetic")
        result=await client.sort_records(
            "synthetic","referrer",1,2,expected_timestamp=100,
        )
        self.assertTrue(result["verified"])
        self.assertTrue(verify_sort(original,client.doc,"referrer",1,2))
        self.assertEqual(len(client.transport.calls),1)
        with self.assertRaises(ConflictError):
            await client.sort_records(
                "synthetic","referrer",1,2,expected_timestamp=100,
            )

    async def test_lost_response_has_no_retry(self):
        client=FakeClient(lost=True)
        with self.assertRaises(VerificationError):
            await client.sort_records(
                "synthetic","referrer",2,1,expected_timestamp=100,
            )
        self.assertEqual(len(client.transport.calls),1)

    def test_sibling_change_invalidates_readback(self):
        before=deepcopy(POPULATED)
        after=deepcopy(POPULATED)
        rows=after["referrer"]["formData"]["referrers"]
        rows[:]=rows[::-1]
        for idx,row in enumerate(rows,1):row["sort"]=idx
        self.assertTrue(verify_sort(before,after,"referrer",1,2))
        rows[0]["company"]="Unexpected company mutation"
        self.assertFalse(verify_sort(before,after,"referrer",1,2))

    async def test_http_and_cli_existing_sort_route(self):
        app=create_app(
            AuthConfig("unused","unused"),api_token=TOKEN,
            allow_experimental_writes=True,
        )
        fake=FakeClient()
        app.state.client=fake
        app.state.idempotency_results={}
        app.state.action_lock=asyncio.Lock()
        headers={
            "Authorization":"Bearer "+TOKEN,
            "If-Match":"100",
            "Idempotency-Key":"synthetic-referrer-sort-key-0001",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),base_url="http://test.invalid",
        ) as http:
            first=await http.put(
                "/v1/tw104/resumes/synthetic/sort/referrer",
                json={"from":1,"to":2},headers=headers,
            )
            replay=await http.put(
                "/v1/tw104/resumes/synthetic/sort/referrer",
                json={"from":1,"to":2},headers=headers,
            )
            reuse=await http.put(
                "/v1/tw104/resumes/synthetic/sort/referrer",
                json={"from":2,"to":1},headers=headers,
            )
        self.assertEqual(
            (first.status_code,replay.status_code,reuse.status_code),
            (200,200,409),
        )
        self.assertEqual(len(fake.transport.calls),1)


if __name__=="__main__":
    unittest.main()
