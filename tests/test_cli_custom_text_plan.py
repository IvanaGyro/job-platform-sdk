"""CUSTOM TEXT only offline request planning through CLI (no credentials)."""
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from job_platforms.cli import _parser, _run

class OfflineCustomTextPlanTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self,args):
        parsed=_parser().parse_args(["custom-text-plan",*args])
        with redirect_stdout(io.StringIO()) as capture:
            await _run(parsed)
        return json.loads(capture.getvalue())

    async def test_create_and_delete_never_connect(self):
        with tempfile.TemporaryDirectory() as d:
            options=Path(d)/"options.json"
            html=Path(d)/"intro.html"
            options.write_text(json.dumps({"optionsCustomTheme":[{"value":3}]}))
            html.write_text("<p>Synthetic introduction</p>",encoding="utf-8")
            made=await self.execute([
                "create","--slot","2","--name","Synthetic text",
                "--html-file",str(html),"--options-file",str(options),
            ])
            self.assertFalse(made["network_sent"])
            self.assertFalse(made["persisted"])
            self.assertEqual(made["body"]["blockValueList"]["custom"]["custom"]["sort"],2)
            removed=await self.execute(["delete","--slot","2"])
            self.assertEqual(
                removed["body"],{"blockValueList":{
                    "custom":{"custom":{"sort":[2]}}
                }},
            )

    async def test_update_from_private_native_form_only(self):
        with tempfile.TemporaryDirectory() as d:
            form=Path(d)/"form.json"
            form.write_text(json.dumps({
                "custom":{
                    "name":"Original",
                    "sort":2,
                    "content":[{
                        "duration":{
                            "startYear":"","startMonth":{},
                            "endYear":"","endMonth":{},
                        },
                        "isInProgress":[],
                        "introduction":"<p>Synthetic</p>",
                        "url":"",
                        "file":[{"type":0,"url":"","ext":""}],
                    }],
                },
                "themeChoose":{"selectedTheme":{"value":3}},
            }))
            edited=await self.execute([
                "update","--slot","2", "--name","New Synthetic",
                "--existing-form-file",str(form),
            ])
            self.assertEqual(
                edited["body"]["blockValueList"]["custom"]["custom"]["name"],
                "New Synthetic",
            )
            with self.assertRaises(ValueError):
                await self.execute([
                    "update","--slot","3", "--name","Wrong slot",
                    "--existing-form-file",str(form),
                ])

    async def test_missing_create_fields_never_connect(self):
        for args in (
            ["create","--slot","1"],
            ["update","--slot","1"],
            ["delete","--slot","1","--name","Unexpected"],
        ):
            with self.subTest(args=args),self.assertRaises(ValueError):
                await self.execute(args)

if __name__=="__main__":
    unittest.main()
