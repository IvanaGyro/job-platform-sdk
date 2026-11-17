"""104 PORTFOLIO native delete + adjacent sort, synthetic fixtures only."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.portfolio_records import (
    portfolio_records, portfolio_delete_body, verify_portfolio_delete,
    portfolio_link_fields, verify_portfolio_link_create,
    portfolio_stable_identity, portfolio_stable_identities,
)
from job_platforms.providers.tw104.record_sort import sort_body, verify_sort

ATTACH = {
    "name": "synthetic.pdf", "status": 0, "url": "",
    "fileId": "synthetic-not-real", "thumbnailFileId": "",
    "src": "", "crawler": False,
}
FIRST = {
    "name": "Synthetic Attachment 1", "attach": deepcopy(ATTACH),
    "attachType": {"text": "File", "value": 1}, "sort": 1,
}
SECOND = {
    "name": "Synthetic Attachment 2", "attach": {
        **deepcopy(ATTACH), "name": "other-synthetic.pdf",
    }, "attachType": {"text": "File", "value": 1}, "sort": 2,
}
POPULATED = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "portfolio": {"formData": {
        "themeChoose": {"selectedTheme": {
            "text": "List", "value": 1, "name": "PortfolioThemeList"
        }},
        "portfolios": [deepcopy(FIRST),deepcopy(SECOND)],
    }},
}
EMPTY = {
    "resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
    "portfolio": {"formData": {}},
}


LINK = {
    "name": "Synthetic Project Link",
    "attachName": "Example link",
    "url": "https://example.invalid/showcase",
}
OPTIONS = {"optionsPortfolioTheme": [{"text": "List", "value": 1}]}


class Transport:
    def __init__(self, owner, *, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.ambiguous = ambiguous

    async def get_json(self, path):
        assert path == "/profile/ajax/options"
        return {"data": deepcopy(OPTIONS)}

    async def request(
        self, method, path, *, params, json_data=None,
        multipart_fields=None,
    ):
        assert path == "/profile/ajax/resumeByBlock/portfolio"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(
            multipart_fields if multipart_fields is not None else json_data
        )))
        form=self.owner.doc["portfolio"]["formData"]
        if method == "POST":
            assert json_data is None
            assert multipart_fields is not None
            if not form:
                form["portfolios"]=[]
                form["themeChoose"]={"selectedTheme":{
                    "text":"List","value":1,"name":"PortfolioThemeList",
                }}
            link=multipart_fields
            form["portfolios"].append({
                "name": link["blockValueList[portfolio][name]"],
                "attach": {
                    "name":link["blockValueList[portfolio][attach][name]"],
                    "status":0,
                    "url":link["blockValueList[portfolio][attach][url]"],
                    "fileId":"",
                    "thumbnailFileId":"",
                    "src":"",
                    "crawler":False,
                },
                "attachType":{"text":"Link","value":2},
                "sort":len(form["portfolios"])+1,
            })
        elif method == "DELETE":
            position=json_data["blockValueList"]["portfolio"]["sort"][0]
            form["portfolios"][:]=[
                x for x in form["portfolios"] if x["sort"]!=position
            ]
            for i,r in enumerate(form["portfolios"],1):
                r["sort"]=i
            if not form["portfolios"]:
                self.owner.doc["portfolio"]["formData"]={}
        else:
            raise AssertionError(method)
        self.owner.doc["resumeTimestamp"]+=1
        if self.ambiguous:
            raise VerificationError("Synthetic response lost")
        return {"data":{}}

    async def put_json(self,path,body,*,params):
        assert path=="/profile/ajax/swapRecordBySort/portfolio"
        self.calls.append(("SORT",deepcopy(body)))
        move=body["blockValueList"]["portfolio"]["portfolios"]["sort"]
        rows=self.owner.doc["portfolio"]["formData"]["portfolios"]
        i,j=move["from"]-1,move["to"]-1
        rows[i],rows[j]=rows[j],rows[i]
        for pos,row in enumerate(rows,1):
            row["sort"]=pos
        self.owner.doc["resumeTimestamp"]+=1
        return {"data":{}}


class Client(Resume104Client):
    def __init__(self, doc=POPULATED, *, ambiguous=False):
        self.doc=deepcopy(doc)
        self.transport=Transport(self,ambiguous=ambiguous)
        self._write_lock=asyncio.Lock()

    async def get_resume(self,version):
        assert version=="synthetic"
        return deepcopy(self.doc)


class PortfolioTests(unittest.IsolatedAsyncioTestCase):
    def test_portfolio_native_delete_contract(self):
        self.assertEqual(
            portfolio_delete_body(POPULATED,position=1),
            {"blockValueList":{"portfolio":{"sort":[1]}}},
        )
        self.assertEqual(portfolio_records(EMPTY),[])
        self.assertEqual(len(portfolio_records(POPULATED)),2)
        with self.assertRaises(UnsupportedWrite):
            portfolio_delete_body(EMPTY,position=1)
        with self.assertRaises(UnsupportedWrite):
            portfolio_delete_body(POPULATED,position=True)

    def test_native_multipart_link_contract(self):
        fields=portfolio_link_fields(POPULATED, LINK)
        self.assertEqual(fields, {
            "blockValueList[portfolio][themeChoose][selectedTheme]":"1",
            "blockValueList[portfolio][name]":"Synthetic Project Link",
            "blockValueList[portfolio][attachType]":"2",
            "blockValueList[portfolio][attach][name]":"Example link",
            "blockValueList[portfolio][attach][url]":
                "https://example.invalid/showcase",
        })
        with self.assertRaises(UnsupportedWrite):
            portfolio_link_fields(EMPTY,LINK)
        self.assertEqual(
            portfolio_link_fields(EMPTY,LINK,options=OPTIONS),
            fields,
        )
        for payload in (
            {**LINK, "url":"javascript:alert(1)"},
            {**LINK, "name":"A"*121},
            {**LINK, "upload": "secret"},
            {**LINK, "url":"https://example.invalid/"+"a"*220},
        ):
            with self.subTest(payload=list(payload)),self.assertRaises(UnsupportedWrite):
                portfolio_link_fields(POPULATED,payload)

    async def test_link_create_preserves_other_attachments(self):
        client=Client()
        before=await client.get_resume("synthetic")
        result=await client.mutate_portfolio(
            "synthetic","create",changes=LINK,expected_timestamp=100,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["position"],3)
        self.assertEqual(len(client.transport.calls),1)
        self.assertEqual(client.transport.calls[0][0],"POST")
        self.assertTrue(verify_portfolio_link_create(
            before,client.doc,
            fields=portfolio_link_fields(before,LINK),
        ))

    async def test_link_first_create_into_empty(self):
        client=Client(EMPTY)
        result=await client.mutate_portfolio(
            "synthetic","create",changes=LINK,expected_timestamp=100,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(len(client.doc["portfolio"]["formData"]["portfolios"]),1)
        self.assertEqual(client.doc["portfolio"]["formData"]["portfolios"][0]["attachType"]["value"],2)

    def test_source_sort_contract(self):
        self.assertEqual(
            sort_body(POPULATED,"portfolio",1,2),
            {"blockValueList":{"portfolio":{"portfolios":{
                "sort":{"from":1,"to":2}
            }}}},
        )

    def test_rejects_bad_media_metadata_without_exposing_contents(self):
        doc=deepcopy(POPULATED)
        doc["portfolio"]["formData"]["portfolios"][0]["attach"]["unknown"]="bad"
        with self.assertRaises(UnsupportedWrite):
            portfolio_records(doc)
        doc=deepcopy(POPULATED)
        doc["portfolio"]["formData"]["portfolios"][0]["sort"]=99
        with self.assertRaises(UnsupportedWrite):
            portfolio_records(doc)
        doc=deepcopy(POPULATED)
        doc["portfolio"]["formData"]["portfolios"][1]["name"]="x"*121
        with self.assertRaises(UnsupportedWrite):
            portfolio_records(doc)

    async def test_delete_preserves_remaining_attachment(self):
        client=Client()
        old=await client.get_resume("synthetic")
        result=await client.mutate_portfolio(
            "synthetic","delete",position=1,expected_timestamp=100,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(len(client.transport.calls),1)
        self.assertTrue(verify_portfolio_delete(
            old,client.doc,position=1,
        ))
        self.assertEqual(
            client.doc["portfolio"]["formData"]["portfolios"][0]["name"],
            "Synthetic Attachment 2"
        )
        with self.assertRaises(ConflictError):
            await client.mutate_portfolio(
                "synthetic","delete",position=1,expected_timestamp=100,
            )

    async def test_delete_last_record_can_reset_empty_form(self):
        single=deepcopy(POPULATED)
        single["portfolio"]["formData"]["portfolios"]=[deepcopy(FIRST)]
        client=Client(single)
        result=await client.mutate_portfolio(
            "synthetic","delete",position=1,expected_timestamp=100,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(client.doc["portfolio"]["formData"],{})

    async def test_ambiguous_never_retries(self):
        client=Client(ambiguous=True)
        with self.assertRaises(VerificationError):
            await client.mutate_portfolio(
                "synthetic","delete",position=1,expected_timestamp=100,
            )
        self.assertEqual(len(client.transport.calls),1)

    async def test_adjacent_portfolio_sort(self):
        client=Client()
        before=await client.get_resume("synthetic")
        result=await client.sort_records(
            "synthetic","portfolio",1,2,expected_timestamp=100,
        )
        self.assertTrue(result["verified"])
        self.assertTrue(verify_sort(
            before,client.doc,"portfolio",1,2,
        ))
        self.assertEqual(client.transport.calls[0][0],"SORT")

    def test_rejects_changes_to_other_attachments(self):
        old=deepcopy(POPULATED)
        after=deepcopy(POPULATED)
        after["portfolio"]["formData"]["portfolios"]=[
            {**deepcopy(SECOND),"sort":1},
        ]
        self.assertTrue(verify_portfolio_delete(old,after,position=1))
        after["portfolio"]["formData"]["portfolios"][0]["attach"]["name"]="different.pdf"
        self.assertFalse(verify_portfolio_delete(old,after,position=1))

    def test_portfolio_signed_file_ids_can_rotate_across_get(self):
        old=deepcopy(POPULATED)
        after=deepcopy(POPULATED)
        after["portfolio"]["formData"]["portfolios"]=[
            {**deepcopy(SECOND),"sort":1},
        ]
        item=after["portfolio"]["formData"]["portfolios"][0]["attach"]
        for volatile in ("fileId","thumbnailFileId","url","src"):
            item[volatile]="https://signed.example.invalid/rotating-access-token"
        item["status"]=1
        self.assertTrue(verify_portfolio_delete(old,after,position=1))
        self.assertEqual(
            portfolio_stable_identity(SECOND),
            portfolio_stable_identity(after["portfolio"]["formData"]["portfolios"][0]),
        )
        self.assertEqual(len(portfolio_stable_identities(old)),2)

    def test_link_create_allows_preexisting_file_token_rotation_only(self):
        old=deepcopy(POPULATED)
        current=deepcopy(POPULATED)
        prev=current["portfolio"]["formData"]["portfolios"][0]["attach"]
        for k in ("url","fileId","thumbnailFileId","src"):
            prev[k]="https://signed.example.invalid/token"
        current["portfolio"]["formData"]["portfolios"].append({
            "name":LINK["name"],
            "attach":{
                "name":LINK["attachName"],"status":0,
                "url":LINK["url"],"fileId":"","thumbnailFileId":"",
                "src":"","crawler":False,
            },
            "attachType":{"text":"Link","value":2},
            "sort":3,
        })
        fields=portfolio_link_fields(old,LINK)
        self.assertTrue(verify_portfolio_link_create(old,current,fields=fields))
        current["portfolio"]["formData"]["portfolios"][1]["name"]="tampered"
        self.assertFalse(verify_portfolio_link_create(old,current,fields=fields))

    def test_duplicate_file_titles_block_ambiguous_identity(self):
        dup=deepcopy(POPULATED)
        dup["portfolio"]["formData"]["portfolios"][1]["name"]=FIRST["name"]
        dup["portfolio"]["formData"]["portfolios"][1]["attach"]["name"]=ATTACH["name"]
        with self.assertRaises(UnsupportedWrite):
            portfolio_stable_identities(dup)



if __name__=="__main__":
    unittest.main()
