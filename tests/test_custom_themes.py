"""104 production theme constants and POST data mapping, synthetic only."""
import base64
from copy import deepcopy
import unittest

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.providers.tw104.custom_themes import (
    THEMES, CONTENT_SLOTS, custom_theme_create_body, custom_theme_capabilities,
)

OPTIONS={"optionsCustomTheme":[{"value":i,"name":name} for i,name in (
    (1,"CustomThemeClassic"),(2,"CustomThemeBanner"),
    (3,"CustomThemeText"),(4,"CustomThemeImage"),
    (5,"CustomThemeMagazine"),
)]}
TEMPLATE={
    "duration":{"startYear":"2023","startMonth":2,
                "endYear":"2024","endMonth":4},
    "isInProgress":False,
    "introduction_html":"<p>Synthetic <strong>item</strong></p>",
    "url":"https://example.invalid/",
    "media":{"type":0},
}
PNG=b"\x89PNG\r\n\x1a\n"+b"\x00"*48
IMAGE={
    "type":1,
    "ext":"png",
    "data_uri":"data:image/png;base64,"+base64.b64encode(PNG).decode(),
}

class ThemesTests(unittest.TestCase):
    def test_all_official_native_theme_ids(self):
        self.assertEqual(THEMES,{
            1:"CLASSIC",2:"BANNER",3:"TEXT",4:"IMAGE",5:"MAGAZINE",
        })

    def test_non_media_layouts_use_one_content_per_item(self):
        for theme, count in ((1, 1), (2, 1), (5, 2)):
            body=custom_theme_create_body(
                slot=1,name="Synthetic layout",theme=theme,
                contents=[deepcopy(TEMPLATE) for _ in range(count)],
                theme_options=OPTIONS,
            )["blockValueList"]["custom"]
            self.assertEqual(body["themeChoose"]["selectedTheme"],theme)
            self.assertEqual(len(body["custom"]["content"]),count)
            item=body["custom"]["content"][0]
            self.assertEqual(item["isInProgress"],0)
            self.assertEqual(item["duration"]["startMonth"],2)
            self.assertEqual(item["file"],[{"type":0,"content":"","ext":""}])

    def test_progress_ongoing_clears_end_fields(self):
        data=deepcopy(TEMPLATE)
        data["isInProgress"]=True
        body=custom_theme_create_body(
            slot=1,name="Ongoing test",theme=1,
            contents=[data],theme_options=OPTIONS,
        )
        row=body["blockValueList"]["custom"]["custom"]["content"][0]
        self.assertEqual(row["isInProgress"],1)
        self.assertEqual(row["duration"]["endYear"],"")
        self.assertEqual(row["duration"]["endMonth"],"")

    def test_very_specific_pure_image_shape(self):
        rows=[{"media":deepcopy(IMAGE)} for _ in range(2)]
        body=custom_theme_create_body(
            slot=5,name="Pure image",theme=4,contents=rows,
            theme_options=OPTIONS,
        )
        content=body["blockValueList"]["custom"]["custom"]["content"]
        self.assertEqual(len(content),1)
        self.assertEqual(set(content[0]),{"file"})
        self.assertEqual(len(content[0]["file"]),2)
        self.assertEqual(content[0]["file"][0]["type"],1)
        self.assertEqual(
            base64.b64decode(content[0]["file"][0]["content"]),PNG,
        )
        self.assertFalse("duration" in content[0])

    def test_video_and_url_media_source_fields(self):
        for media,kind,value in (
            ({"type":2,"fileId":"synthetic-file-id","ext":"mp4"},
             2,"synthetic-file-id"),
            ({"type":3,"url":"https://example.invalid/video","ext":""},
             3,"https://example.invalid/video"),
        ):
            data=deepcopy(TEMPLATE)
            data["media"]=media
            body=custom_theme_create_body(
                slot=1,name="Synthetic",theme=5,
                contents=[deepcopy(data), data],theme_options=OPTIONS,
            )
            content=body["blockValueList"]["custom"]["custom"]["content"][0]["file"][0]
            self.assertEqual((content["type"],content["content"]),(kind,value))

    def test_text_falls_back_to_real_verified_text_serializer(self):
        body=custom_theme_create_body(
            slot=1,name="Synthetic",theme=3,
            contents=[{"introduction_html":"<p>Text</p>"}],
            theme_options=OPTIONS,
        )
        row=body["blockValueList"]["custom"]["custom"]["content"][0]
        self.assertEqual(row["file"],[{"type":0,"content":"","ext":""}])

    def test_exact_source_theme_content_slots_and_write_support(self):
        self.assertEqual(CONTENT_SLOTS, {1: 1, 2: 1, 3: 1, 4: 2, 5: 2})
        catalog = custom_theme_capabilities()
        self.assertFalse(catalog["current_site_availability_verified"])
        self.assertFalse(catalog["persisted"])
        self.assertTrue(catalog["read_only"])
        self.assertEqual([x["value"] for x in catalog["themes"]], [1,2,3,4,5])
        self.assertEqual([x["frontend_content_slots"] for x in catalog["themes"]],
                         [1,1,1,2,2])
        from job_platforms.providers.tw104.client import Resume104Client
        self.assertEqual(Resume104Client.supported_custom_themes(), catalog)
        self.assertEqual([x["writer_scope"] for x in catalog["themes"]], [
            "single-no-media", "single-no-media", "single-text",
            "offline-planner", "offline-planner",
        ])

    def test_serializer_refuses_excess_or_incomplete_theme_content(self):
        for theme, count, row in (
            (1, 2, TEMPLATE), (2, 2, TEMPLATE),
            (5, 1, TEMPLATE), (5, 3, TEMPLATE),
            (4, 3, {"media": IMAGE}),
        ):
            with self.subTest(theme=theme, count=count):
                with self.assertRaisesRegex(UnsupportedWrite, "content count"):
                    custom_theme_create_body(
                        slot=1, name="Synthetic", theme=theme,
                        contents=[deepcopy(row) for _ in range(count)],
                        theme_options=OPTIONS,
                    )
        for count in (1, 2):
            self.assertEqual(
                len(custom_theme_create_body(
                    slot=1, name="Synthetic", theme=4,
                    contents=[{"media": deepcopy(IMAGE)} for _ in range(count)],
                    theme_options=OPTIONS,
                )["blockValueList"]["custom"]["custom"]["content"][0]["file"]),
                count,
            )

    def test_no_media_and_markup_injection_rejected(self):
        invalid=[
            (1,{**deepcopy(TEMPLATE),"media":{"type":0,"fileId":"danger"}}),
            (1,{**deepcopy(TEMPLATE),"url":"javascript:bad()"}),
            (1,{**deepcopy(TEMPLATE),"introduction_html":"<script>x</script>"}),
            (1,{**deepcopy(TEMPLATE),"duration":{"startYear":"2023"}}),
            (1,{**deepcopy(TEMPLATE),"isInProgress":1}),
            (4,{"media":{"type":1,"ext":"png","data_uri":"data:image/png;base64,XX!"}}),
            (4,{"media":{"type":1,"ext":"png","data_uri":"data:image/png;base64,"+base64.b64encode(b"bad png").decode()}}),
            (4,{"media":{"type":3,"ext":"","url":"https://example.invalid/"}}),
        ]
        for theme,entry in invalid:
            with self.subTest(theme=theme,entry=list(entry)):
                with self.assertRaises(UnsupportedWrite):
                    custom_theme_create_body(
                        slot=1,name="Bad",theme=theme,
                        contents=[entry],theme_options=OPTIONS,
                    )
        with self.assertRaises(UnsupportedWrite):
            custom_theme_create_body(
                slot=1,name="Too many",theme=1,
                contents=[deepcopy(TEMPLATE)]*7,theme_options=OPTIONS,
            )

if __name__=="__main__":
    unittest.main()
