"""104 UNDER18 source-only synthetic CRUD: no real age identity information."""
import asyncio
from copy import deepcopy
import unittest
from httpx import ASGITransport, AsyncClient
from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.http_api import create_app
from job_platforms.providers.tw104.auth import AuthConfig
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.under18_records import (
    under18_fields, under18_native_form, under18_operation_body,
)

DATA={"birthdayDocument":"synthetic-token-not-a-person", "idType":0,
      "selfIdentityConfirmed":False}
CHANGED={"birthdayDocument":"synthetic-second-token", "idType":1,
         "selfIdentityConfirmed":True}
BASE={"resume":{"vno":"synthetic"},"resumeTimestamp":123,
      "bio":{"formData":{"bio":{"chi":"Synthetic BIO","eng":""}}},
      "under18":{"formData":{}}}
TOKEN="synthetic-bearer-token-under18-00000000000001"
URL="/v1/tw104/resumes/synthetic/under18"

class Transport:
    def __init__(self, client, *, fail=False):
        self.client=client
        self.calls=[]
        self.fail=fail
    async def request(self, method, path, *, params, json_data):
        assert path=="/profile/ajax/resumeByBlock/under18"
        assert params=={"vno":"synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        self.client.doc["under18"]["formData"]={
            "under18": deepcopy(json_data["blockValueList"]["under18"])}
        self.client.doc["resumeTimestamp"]+=1
        if self.fail:
            raise VerificationError("simulated uncertain write")
        return {"data":{}}

class Client(Resume104Client):
    def __init__(self, *, fail=False):
        self.doc=deepcopy(BASE)
        self._write_lock=asyncio.Lock()
        self.transport=Transport(self, fail=fail)
    async def get_resume(self, resume_id):
        assert resume_id=="synthetic"
        return deepcopy(self.doc)

class Under18SDKTests(unittest.IsolatedAsyncioTestCase):
    def test_source_mapped_payload_and_unknown_fields(self):
        self.assertEqual(under18_operation_body(BASE,"create",changes=DATA),{
            "blockValueList":{"under18":DATA}})
        existing=deepcopy(BASE)
        existing["under18"]["formData"]={"under18":deepcopy(DATA)}
        self.assertEqual(under18_operation_body(existing,"update",changes=CHANGED),{
            "blockValueList":{"under18":CHANGED}})
        self.assertEqual(under18_native_form(existing),DATA)
        for bad in ({}, {**DATA,"unknown":"do-not-echo"},
                    {**DATA,"birthdayDocument":34},
                    {**DATA,"birthdayDocument":"x\n"},
                    {**DATA,"birthdayDocument":"x"*1025},
                    {**DATA,"idType":True}, {**DATA,"idType":-1},
                    {**DATA,"idType":1001},
                    {**DATA,"selfIdentityConfirmed":1}):
            with self.subTest(bad_type=str(type(bad))):
                with self.assertRaises(UnsupportedWrite) as exc:
                    under18_fields(bad)
                self.assertNotIn("do-not-echo",str(exc.exception))
    def test_state_collision_and_incomplete_form_fail_closed(self):
        existing=deepcopy(BASE)
        existing["under18"]["formData"]={"under18":deepcopy(DATA)}
        for doc,action,payload in ((existing,"create",CHANGED),
                                   (BASE,"update",CHANGED),
                                   (existing,"update",DATA),
                                   (existing,"delete",CHANGED)):
            with self.subTest(action=action), self.assertRaises(UnsupportedWrite):
                under18_operation_body(doc,action,changes=payload)
        existing["under18"]["formData"]["unexpected"]="extra"
        with self.assertRaises(UnsupportedWrite):
            under18_operation_body(existing,"update",changes=CHANGED)
    async def test_create_update_and_consent_required(self):
        c=Client()
        with self.assertRaises(UnsupportedWrite):
            await c.mutate_under18("synthetic","create",changes=DATA,
                                   expected_timestamp=123)
        self.assertEqual(c.transport.calls,[])
        result=await c.mutate_under18("synthetic","create",changes=DATA,
                       expected_timestamp=123,acknowledge_identity_write=True)
        self.assertTrue(result["verified"])
        self.assertNotIn(DATA["birthdayDocument"],str(result))
        await c.mutate_under18("synthetic","update",changes=CHANGED,
                       expected_timestamp=124,acknowledge_identity_write=True)
        self.assertEqual([x[0] for x in c.transport.calls],["POST","PUT"])
        self.assertEqual(under18_native_form(c.doc),CHANGED)
        self.assertEqual(c.doc["bio"],BASE["bio"])
    async def test_wrong_stored_identity_value_is_not_claimed_verified(self):
        c=Client()
        original=c.transport.request
        async def apply_wrong_value(method,path,*,params,json_data):
            response=await original(method,path,params=params,json_data=json_data)
            c.doc["under18"]["formData"]["under18"]["idType"]=99
            return response
        c.transport.request=apply_wrong_value
        with self.assertRaises(VerificationError):
            await c.mutate_under18("synthetic","create",changes=DATA,
                       expected_timestamp=123,acknowledge_identity_write=True)
        self.assertEqual(len(c.transport.calls),1)

    async def test_stale_ambiguous_and_cross_block_damage(self):
        c=Client()
        with self.assertRaises(ConflictError):
            await c.mutate_under18("synthetic","create",changes=DATA,
                       expected_timestamp="None",acknowledge_identity_write=True)
        self.assertEqual(c.transport.calls,[])
        c=Client(fail=True)
        with self.assertRaises(VerificationError):
            await c.mutate_under18("synthetic","create",changes=DATA,
                       expected_timestamp=123,acknowledge_identity_write=True)
        self.assertEqual(len(c.transport.calls),1)
        c=Client()
        original=c.transport.request
        async def corrupt(method,path,*,params,json_data):
            response=await original(method,path,params=params,json_data=json_data)
            c.doc["bio"]["formData"]["bio"]["chi"]="clobbered"
            return response
        c.transport.request=corrupt
        with self.assertRaises(VerificationError):
            await c.mutate_under18("synthetic","create",changes=DATA,
                       expected_timestamp=123,acknowledge_identity_write=True)
        self.assertEqual(len(c.transport.calls),1)

class Under18HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app=create_app(AuthConfig("unused","unused"),api_token=TOKEN,
                            allow_experimental_writes=True)
        self.client=Client()
        self.app.state.client=self.client
        self.app.state.action_lock=asyncio.Lock()
        self.app.state.idempotency_results={}
        self.http=AsyncClient(transport=ASGITransport(app=self.app),
                              base_url="http://local.invalid")
        await self.http.__aenter__()
    async def asyncTearDown(self):
        await self.http.__aexit__(None,None,None)
    def headers(self,version,key,*,ack=True):
        return {"Authorization":"Bearer "+TOKEN,"If-Match":str(version),
                "Idempotency-Key":key,
                **({"X-Identity-Write-Acknowledgement":"true"} if ack else {})}
    async def test_auth_consent_idempotency_and_post_put(self):
        unauth=await self.http.post(URL,json=DATA)
        noack=await self.http.post(URL,json=DATA,
            headers=self.headers(123,"synthetic-under18-consent-0001",ack=False))
        self.assertEqual((unauth.status_code,noack.status_code),(401,428))
        self.assertEqual(self.client.transport.calls,[])
        hdr=self.headers(123,"synthetic-under18-create-0001")
        first=await self.http.post(URL,json=DATA,headers=hdr)
        replay=await self.http.post(URL,json=DATA,headers=hdr)
        collision=await self.http.post(URL,json=CHANGED,headers=hdr)
        update=await self.http.put(URL,json=CHANGED,
              headers=self.headers(124,"synthetic-under18-update-0001"))
        self.assertEqual(tuple(x.status_code for x in (first,replay,collision,update)),
                         (200,200,409,200))
        self.assertNotIn(DATA["birthdayDocument"],first.text)
        self.assertNotIn(CHANGED["birthdayDocument"],update.text)
        self.assertNotIn(DATA["birthdayDocument"], str(self.app.state.idempotency_results))
        self.assertNotIn(CHANGED["birthdayDocument"], str(self.app.state.idempotency_results))
        self.assertEqual([x[0] for x in self.client.transport.calls],["POST","PUT"])
    async def test_native_duplicate_create_and_uninitialized_update_fail_early(self):
        not_yet=await self.http.put(URL,json=CHANGED,
              headers=self.headers(123,"synthetic-under18-missing-update-0001"))
        self.assertEqual(not_yet.status_code,422)
        self.assertEqual(self.app.state.idempotency_results,{})
        self.client.doc["under18"]["formData"]={"under18":deepcopy(DATA)}
        duplicate=await self.http.post(URL,json=CHANGED,
              headers=self.headers(123,"synthetic-under18-duplicate-0001"))
        self.assertEqual(duplicate.status_code,422)
        self.assertEqual(self.app.state.idempotency_results,{})
        self.assertEqual(self.client.transport.calls,[])

    async def test_invalid_or_stale_does_not_reserve_key(self):
        invalid=await self.http.post(URL,json={**DATA,"idType":True},
              headers=self.headers(123,"synthetic-under18-invalid-0001"))
        stale=await self.http.post(URL,json=DATA,
              headers=self.headers(122,"synthetic-under18-stale-0001"))
        self.assertEqual((invalid.status_code,stale.status_code),(422,412))
        self.assertEqual(self.app.state.idempotency_results,{})
        self.assertEqual(self.client.transport.calls,[])
    async def test_uncertain_write_never_replays(self):
        self.client=Client(fail=True)
        self.app.state.client=self.client
        headers=self.headers(123,"synthetic-under18-uncertain-0001")
        first=await self.http.post(URL,json=DATA,headers=headers)
        replay=await self.http.post(URL,json=DATA,headers=headers)
        self.assertEqual((first.status_code,replay.status_code),(409,409))
        self.assertEqual([x[0] for x in self.client.transport.calls],["POST"])
    async def test_disabled_writer(self):
        app=create_app(AuthConfig("unused","unused"),api_token=TOKEN,
                       allow_experimental_writes=False)
        app.state.client=Client()
        app.state.action_lock=asyncio.Lock()
        app.state.idempotency_results={}
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://local.invalid") as http:
            result=await http.post(URL,json=DATA,
                  headers=self.headers(123,"synthetic-under18-disabled-0001"))
        self.assertEqual(result.status_code,501)
        self.assertEqual(app.state.client.transport.calls,[])


if __name__=="__main__":unittest.main()
