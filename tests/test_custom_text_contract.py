"""Safe source-level 104 CUSTOM TEXT=3 contract; no network writes."""
from copy import deepcopy
import unittest

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.providers.tw104.custom_text_contract import (
    TEXT_THEME, custom_delete_body, custom_text_create_body,
    custom_text_update_body,
)

OPTIONS = {"optionsCustomTheme": [
    {"value": 1, "name": "CustomThemeClassic"},
    {"value": 3, "name": "CustomThemeText"},
    {"value": 4, "name": "CustomThemeImage"},
]}
INITIAL = {
    "custom": {
        "name": "Synthetic Free Text",
        "sort": 2,
        "content": [{
            "duration": {
                "startYear": "", "startMonth": {},
                "endYear": "", "endMonth": {},
            },
            "isInProgress": [],
            "introduction": "<p>Example</p>",
            "url": "",
            "file": [{"type": 0, "url": "", "src": "", "ext": ""}],
        }],
    },
    "themeChoose": {"selectedTheme": {
        "value": TEXT_THEME, "name": "CustomThemeText",
    }},
}


class CustomTextTests(unittest.TestCase):
    def test_theme_text_source_mapped_first_create(self):
        body=custom_text_create_body(
            slot=2, name="Synthetic Free Text",
            introduction_html="<p>Example</p>",theme_options=OPTIONS,
        )
        self.assertEqual(body,{
            "blockValueList":{"custom":{
                "custom":{
                    "name":"Synthetic Free Text","sort":2,
                    "content":[{
                        "duration":{
                            "startYear":"","startMonth":"",
                            "endYear":"","endMonth":"",
                        },
                        "isInProgress":0,
                        "introduction":"<p>Example</p>",
                        "url":"",
                        "file":[{"type":0,"content":"","ext":""}],
                    }],
                },
                "themeChoose":{"selectedTheme":3},
            }},
        })
        self.assertNotIn("img",str(body))
        self.assertNotIn("fileId",str(body))

    def test_custom_slot_delete_shape_source_matched(self):
        self.assertEqual(
            custom_delete_body(slot=3),
            {"blockValueList":{"custom":{"custom":{"sort":[3]}}}},
        )

    def test_exact_source_theme_values_and_dynamic_slot_limits(self):
        for slot in (0,7,-1,None,True,"1",1.0):
            with self.subTest(slot=slot),self.assertRaises(UnsupportedWrite):
                custom_delete_body(slot=slot)
        for options in ({},{"optionsCustomTheme":[]},
                        {"optionsCustomTheme":[{"value":4}]}):
            with self.subTest(options=options),self.assertRaises(UnsupportedWrite):
                custom_text_create_body(
                    slot=1,name="Synthetic",
                    introduction_html="<p>Test</p>",theme_options=options,
                )

    def test_rejects_media_like_markup_and_oversize(self):
        invalid=[
            ("name","x"*31),
            ("name",""),
            ("introduction_html","<script>alert(1)</script>"),
            ("introduction_html",'<img src="x">'),
            ("introduction_html",'<a href="https://example.invalid">link</a>'),
            ("introduction_html",'<p onmouseover="x">foo</p>'),
            ("introduction_html","x"*4001),
        ]
        for field,value in invalid:
            with self.subTest(field=field,value_type=type(value).__name__):
                kwargs={
                    "slot":1,"name":"Synthetic",
                    "introduction_html":"<p>Test</p>",
                    "theme_options":OPTIONS,
                }
                kwargs[field]=value
                with self.assertRaises(UnsupportedWrite):
                    custom_text_create_body(**kwargs)

    def test_safe_text_only_update_preserves_form_structure(self):
        body=custom_text_update_body(
            INITIAL,name="Renamed Synthetic",
            introduction_html="<p>New <strong>example</strong></p>",
        )
        assert body["blockValueList"]["custom"]["custom"]["sort"] == 2
        record=body["blockValueList"]["custom"]["custom"]
        self.assertEqual(record["name"],"Renamed Synthetic")
        self.assertEqual(
            record["content"][0]["introduction"],
            "<p>New <strong>example</strong></p>",
        )
        self.assertEqual(record["content"][0]["file"][0]["type"],0)

    def test_unsafe_existing_media_or_multi_content_fails_closed(self):
        cases=[]
        img=deepcopy(INITIAL)
        img["custom"]["content"][0]["file"][0]["type"]=1
        cases.append(img)
        disguised_media=deepcopy(INITIAL)
        disguised_media["custom"]["content"][0]["file"][0]["fileId"]="hidden-id"
        cases.append(disguised_media)
        extra_duration=deepcopy(INITIAL)
        extra_duration["custom"]["content"][0]["duration"]["unexpected"]="hidden"
        cases.append(extra_duration)
        second=deepcopy(INITIAL)
        second["custom"]["content"].append(deepcopy(second["custom"]["content"][0]))
        cases.append(second)
        other_theme=deepcopy(INITIAL)
        other_theme["themeChoose"]["selectedTheme"]["value"]=4
        cases.append(other_theme)
        extras=deepcopy(INITIAL)
        extras["custom"]["content"][0]["metadata"]="unexpected"
        cases.append(extras)
        dates=deepcopy(INITIAL)
        dates["custom"]["content"][0]["duration"]["startYear"]="2024"
        cases.append(dates)
        bad_url=deepcopy(INITIAL)
        bad_url["custom"]["content"][0]["url"]="https://example.invalid"
        cases.append(bad_url)
        for case in cases:
            with self.subTest(fields=str(list(case["custom"]))):
                with self.assertRaises(UnsupportedWrite):
                    custom_text_update_body(case,name="New")
        with self.assertRaises(UnsupportedWrite):
            custom_text_update_body(INITIAL)


if __name__=="__main__":
    unittest.main()
