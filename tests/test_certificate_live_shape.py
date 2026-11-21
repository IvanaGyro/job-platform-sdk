"""Synthetic regressions for REAL observed 104 CERTIFICATE GET shape.

A 2026-11-17 private write/read/restore test observed
formData.certificate={others:TEXT,certifications:[]}, without
the previously assumed certificates key. No private text included.
"""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite
from job_platforms.core.patch import EditPlan,JsonPatchOperation
from job_platforms.providers.tw104.certificate_block_actions import (
    certificate_block_body,verify_certificate_block,
)
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.writers import (
    certificate_data,section_request_body,
)

EMPTY={
    "resume":{"vno":"synthetic"},"resumeTimestamp":100,
    "certificate":{"formData":{},"success":True},
}
REAL={
    "resume":{"vno":"synthetic"},"resumeTimestamp":101,
    "certificate":{"formData":{
        "themeChoose":{"selectedTheme":{
            "text":"Synthetic certificate theme","value":1,
            "name":"CertificateThemeList",
        }},
        "certificate":{
            "others":"Synthetic certificate text",
            "certifications":[],
        },
    },"success":True},
}
LINKED=deepcopy(REAL)
LINKED["certificate"]["formData"]["certificate"]["certifications"]=[
    {"category":"synthetic","items":[{"id":123}]}
]


class NativeTransport:
    def __init__(self,owner):
        self.owner=owner
        self.calls=[]

    async def request(self,method,path,*,params,json_data):
        assert path=="/profile/ajax/resumeByBlock/certificate"
        assert params=={"vno":"synthetic"}
        self.calls.append((method,deepcopy(json_data)))
        item=json_data["blockValueList"]["certificate"]
        if method=="PUT":
            self.owner.doc["certificate"]=deepcopy(REAL["certificate"])
            self.owner.doc["certificate"]["formData"]["certificate"]["others"]=item["others"]
        elif method=="DELETE":
            assert item=={"certificates":"","others":""}
            self.owner.doc["certificate"]=deepcopy(EMPTY["certificate"])
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"]+=1
        return {"data":{}}

    async def put_json(self,path,body,*,params):
        return await self.request(
            "PUT",path,params=params,json_data=body,
        )


class Client(Resume104Client):
    def __init__(self,doc):
        self.doc=deepcopy(doc)
        self.transport=NativeTransport(self)
        self._write_lock=asyncio.Lock()

    async def get_resume(self,version):
        assert version=="synthetic"
        return deepcopy(self.doc)


class RealCertificateShapeTests(unittest.IsolatedAsyncioTestCase):
    def test_read_without_certificates_field_is_supported(self):
        self.assertEqual(
            certificate_data(REAL),
            {"certificates":[],"others":"Synthetic certificate text"},
        )
        self.assertEqual(section_request_body(REAL,"certificate"),{
            "blockValueList":{"certificate":{
                "certificates":[],"others":"Synthetic certificate text",
            }}
        })
        self.assertEqual(
            certificate_block_body(REAL,"clear"),
            {"blockValueList":{"certificate":{"certificates":"","others":""}}},
        )

    def test_live_shape_readback_and_restore_are_verified(self):
        body=certificate_block_body(
            EMPTY,"initialize",others="Synthetic certificate text",
        )
        self.assertTrue(
            verify_certificate_block(EMPTY,REAL,"initialize",body=body)
        )
        self.assertTrue(
            verify_certificate_block(
                REAL,EMPTY,"clear",
                body=certificate_block_body(REAL,"clear"),
            )
        )
        unexpected=deepcopy(REAL)
        unexpected["certificate"]["formData"]["certificate"]["others"]="Other"
        self.assertFalse(
            verify_certificate_block(EMPTY,unexpected,"initialize",body=body)
        )

    async def test_sdk_first_put_and_clear_against_real_shape(self):
        c=Client(EMPTY)
        result=await c.mutate_certificate_block(
            "synthetic","initialize",
            expected_timestamp=100,others="Synthetic certificate text",
        )
        self.assertTrue(result["verified"])
        self.assertEqual(
            list(c.doc["certificate"]["formData"]["certificate"]),
            ["others","certifications"],
        )
        removed=await c.mutate_certificate_block(
            "synthetic","clear",expected_timestamp=101,
        )
        self.assertTrue(removed["verified"])
        self.assertEqual(c.doc["certificate"]["formData"],{})
        self.assertEqual([x[0] for x in c.transport.calls],["PUT","DELETE"])

    async def test_patch_only_others_on_live_shape(self):
        client=Client(REAL)
        plan=EditPlan(
            "synthetic",101,
            [JsonPatchOperation(
                "replace","/certificate/formData/certificate/others",
                "Revised synthetic text",
            )],
        )
        result=await client.save_edit(plan)
        self.assertTrue(result["verified"])
        self.assertEqual(result["verified_sections"],["certificate"])
        self.assertEqual(
            client.doc["certificate"]["formData"]["certificate"]["others"],
            "Revised synthetic text",
        )
        wire=client.transport.calls[0][1]
        self.assertEqual(wire["blockValueList"]["certificate"],{
            "certificates":[],"others":"Revised synthetic text",
        })

    def test_missing_link_representation_is_not_fabricated(self):
        bad=deepcopy(REAL)
        bad["certificate"]["formData"]["certificate"].pop("certifications")
        with self.assertRaises(UnsupportedWrite):
            certificate_data(bad)
        with self.assertRaises(UnsupportedWrite):
            certificate_block_body(bad,"clear")

    def test_attached_certification_records_block_clear_and_patch(self):
        with self.assertRaises(UnsupportedWrite):
            certificate_block_body(LINKED,"clear")
        with self.assertRaises(UnsupportedWrite):
            certificate_data(LINKED)

    async def test_stale_timestamp_before_native_mutation(self):
        c=Client(REAL)
        with self.assertRaises(ConflictError):
            await c.mutate_certificate_block(
                "synthetic","clear",expected_timestamp=100,
            )
        self.assertEqual(c.transport.calls,[])


if __name__=="__main__":
    unittest.main()
