"""Synthetic, redacted reconstruction of live custom1 104 GET and CRUD."""
from copy import deepcopy
import asyncio
import unittest

from job_platforms.core.errors import UnsupportedWrite,VerificationError,ConflictError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.custom_text_contract import (
    custom_text_form,verify_custom_text_mutation,custom_text_create_body,
    custom_text_update_body,custom_delete_body,
)
from test_custom_text_contract import OPTIONS

BASE={"resume":{"vno":"synthetic"},"resumeTimestamp":100}
FORM={
    "custom":{"name":"Synthetic custom","sort":1,"content":[{
        "duration":{"startYear":"","startMonth":{},
                    "endYear":"","endMonth":{}},
        "isInProgress":[],"introduction":"<p>Synthetic text</p>",
        "url":"",
        "file":[{
            "type":0,"fileId":"","url":"",
            "thumbnailStatus":"","thumbnailUrl":"",
        }],
    }]},
    "themeChoose":{"selectedTheme":{
        "text":"Text","value":3,"name":"CustomThemeText",
    }},
}
CREATED=deepcopy(BASE)
CREATED["custom1"]={"formData":deepcopy(FORM)}
CREATED["resumeTimestamp"]=101

class Transport:
    def __init__(self,owner,lost=False):
        self.owner=owner
        self.calls=[]
        self.lost=lost
    async def get_json(self,path):
        assert path=="/profile/ajax/options"
        return {"data":deepcopy(OPTIONS)}
    async def request(self,method,path,*,params,json_data):
        assert params=={"vno":"synthetic"}
        assert path=="/profile/ajax/resumeByBlock/custom"
        self.calls.append((method,deepcopy(json_data)))
        if method=="DELETE":
            assert json_data==custom_delete_body(slot=1)
            del self.owner.doc["custom1"]
        else:
            item=json_data["blockValueList"]["custom"]["custom"]
            self.owner.doc["custom1"]={"formData":deepcopy(FORM)}
            self.owner.doc["custom1"]["formData"]["custom"]["name"]=item["name"]
            self.owner.doc["custom1"]["formData"]["custom"]["content"][0][
                "introduction"
            ]=item["content"][0]["introduction"]
        self.owner.doc["resumeTimestamp"]+=1
        if self.lost:raise VerificationError("Simulated uncertain request")
        return {"data":{}}

class Client(Resume104Client):
    def __init__(self,doc=BASE,lost=False):
        self.doc=deepcopy(doc)
        self.transport=Transport(self,lost)
        self._write_lock=asyncio.Lock()
    async def get_resume(self,vno):
        assert vno=="synthetic"
        return deepcopy(self.doc)

class CustomTextRealShapeTests(unittest.IsolatedAsyncioTestCase):
    def test_live_native_fields_and_readback(self):
        self.assertEqual(custom_text_form(BASE,slot=1),None)
        self.assertEqual(custom_text_form(CREATED,slot=1),FORM)
        body=custom_text_create_body(
            slot=1,name="Synthetic custom",
            introduction_html="<p>Synthetic text</p>",theme_options=OPTIONS,
        )
        self.assertTrue(verify_custom_text_mutation(
            BASE,CREATED,"create",slot=1,body=body,
        ))
        updated=deepcopy(CREATED)
        updated["custom1"]["formData"]["custom"]["name"]="Changed"
        body=custom_text_update_body(FORM,name="Changed")
        self.assertTrue(verify_custom_text_mutation(
            CREATED,updated,"update",slot=1,body=body,
        ))
        self.assertTrue(verify_custom_text_mutation(
            CREATED,BASE,"delete",slot=1,body=custom_delete_body(slot=1),
        ))

    async def test_complete_sdk_create_update_delete(self):
        c=Client()
        made=await c.mutate_custom_text(
            "synthetic","create",slot=1,expected_timestamp=100,
            name="Synthetic custom",introduction_html="<p>Synthetic text</p>",
        )
        self.assertTrue(made["verified"])
        self.assertEqual(made["theme"],"TEXT")
        changed=await c.mutate_custom_text(
            "synthetic","update",slot=1,expected_timestamp=101,
            name="Changed",introduction_html="<p>Changed</p>",
        )
        self.assertTrue(changed["verified"])
        cleared=await c.mutate_custom_text(
            "synthetic","delete",slot=1,expected_timestamp=102,
        )
        self.assertTrue(cleared["verified"])
        self.assertNotIn("custom1",c.doc)
        self.assertEqual([x[0] for x in c.transport.calls],[
            "POST","PUT","DELETE",
        ])

    async def test_safety_no_mutation_on_stale_or_unsupported_media(self):
        c=Client(CREATED)
        with self.assertRaises(ConflictError):
            await c.mutate_custom_text(
                "synthetic","delete",slot=1,expected_timestamp=100,
            )
        with self.assertRaises(UnsupportedWrite):
            await c.mutate_custom_text(
                "synthetic","create",slot=1,expected_timestamp=101,
                name="Duplicate",introduction_html="<p>Hi</p>",
            )
        with self.assertRaises(UnsupportedWrite):
            await c.mutate_custom_text(
                "synthetic","update",slot=1,expected_timestamp=101,
                introduction_html="<img src='unsafe'>",
            )
        self.assertEqual(c.transport.calls,[])
        bad=deepcopy(CREATED)
        bad["custom1"]["formData"]["custom"]["content"][0]["file"][0][
            "fileId"
        ]="existing-file"
        c=Client(bad)
        with self.assertRaises(UnsupportedWrite):
            await c.mutate_custom_text(
                "synthetic","delete",slot=1,expected_timestamp=101,
            )
        self.assertEqual(c.transport.calls,[])

    async def test_failed_write_never_blindly_retries(self):
        c=Client(lost=True)
        with self.assertRaises(VerificationError):
            await c.mutate_custom_text(
                "synthetic","create",slot=1,expected_timestamp=100,
                name="Synthetic custom",introduction_html="<p>Synthetic text</p>",
            )
        self.assertEqual(len(c.transport.calls),1)

    def test_reject_unobserved_custom_values(self):
        bad=deepcopy(CREATED)
        bad["custom1"]["formData"]["custom"]["content"][0][
            "file"
        ][0]["thumbnailStatus"]="READY"
        with self.assertRaises(UnsupportedWrite):
            custom_text_form(bad,slot=1)
        bad=deepcopy(CREATED)
        bad["custom1"]["formData"]["custom"]["content"][0][
            "file"
        ][0]["type"]=1
        with self.assertRaises(UnsupportedWrite):
            custom_text_form(bad,slot=1)
        bad=deepcopy(CREATED)
        bad["custom1"]["formData"]["themeChoose"]["selectedTheme"]["value"]=1
        with self.assertRaises(UnsupportedWrite):
            custom_text_form(bad,slot=1)

if __name__=="__main__":
    unittest.main()
