"""104 PORTFOLIO native delete + adjacent sort, synthetic fixtures only."""
import asyncio
from copy import deepcopy
import unittest

from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.portfolio_records import (
    portfolio_records, portfolio_delete_body, verify_portfolio_delete,
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


class Transport:
    def __init__(self, owner, *, ambiguous=False):
        self.owner = owner
        self.calls = []
        self.ambiguous = ambiguous

    async def request(self, method, path, *, params, json_data):
        assert method=="DELETE"
        assert path=="/profile/ajax/resumeByBlock/portfolio"
        assert params=={"vno":"synthetic"}
        self.calls.append((method,deepcopy(json_data)))
        position=json_data["blockValueList"]["portfolio"]["sort"][0]
        form=self.owner.doc["portfolio"]["formData"]
        form["portfolios"][:]=[
            x for x in form["portfolios"] if x["sort"]!=position
        ]
        for i,r in enumerate(form["portfolios"],1):
            r["sort"]=i
        if not form["portfolios"]:
            self.owner.doc["portfolio"]["formData"]={}
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
        after["portfolio"]["formData"]["portfolios"][0]["attach"]["fileId"]="unexpected"
        self.assertFalse(verify_portfolio_delete(old,after,position=1))


if __name__=="__main__":
    unittest.main()
