"""104 PROJECT real GET shape from synthetic-redacted live November 17 probe."""
from copy import deepcopy
import unittest

from job_platforms.core.errors import UnsupportedWrite
from job_platforms.providers.tw104.project_records import (
    project_records, project_operation_body, verify_project_operation,
)
from test_project_records import (
    EMPTY, POPULATED, OPTIONS, CHANGES,
)

REAL_ROW = {
    **deepcopy(CHANGES),
    "duration":{
        "startYear":"2023",
        "startMonth":{"text":"January","value":1},
        "endYear":"2024",
        "endMonth":{"text":"December","value":12},
    },
    "isInProgress":[],
    "img":{
        "type":0, "fileId":"", "url":"",
        "thumbnailStatus":"", "thumbnailUrl":"",
    },
    "sort":1,
}

AFTER={
    "resume":{"vno":"synthetic"},"resumeTimestamp":101,
    "project":{"formData":{
        "themeChoose":{"selectedTheme":{
            "text":"One column","value":1,"name":"ProjectTheme1Column",
        }},
        "projects":[deepcopy(REAL_ROW)],
    }},
}

MEDIA_SIBLING = {
    **deepcopy(REAL_ROW),
    "name":"Preexisting synthetic media record",
    "img":{
        "type":1,"fileId":"synthetic-existing-image-id",
        "url":"https://example.invalid/image.jpg",
        "thumbnailStatus":"SUCCESS","thumbnailUrl":"",
    },
}

BASE_MEDIA=deepcopy(AFTER)
BASE_MEDIA["project"]["formData"]["projects"]=[deepcopy(MEDIA_SIBLING)]
BASE_MEDIA["resumeTimestamp"]=100

TWO_ROWS=deepcopy(AFTER)
TWO_ROWS["project"]["formData"]["projects"]=[
    deepcopy(MEDIA_SIBLING),{**deepcopy(REAL_ROW),"sort":2},
]


class ProjectNativeLiveShapeTests(unittest.TestCase):
    def test_real_month_option_progress_and_empty_img_normalize(self):
        self.assertEqual(len(project_records(AFTER)),1)
        request=project_operation_body(
            EMPTY,"create",changes=CHANGES,options=OPTIONS,
        )
        self.assertTrue(verify_project_operation(
            EMPTY,AFTER,"create",body=request,position=None,
        ))

    def test_media_sibling_preserved_when_creating_new_no_media(self):
        create=project_operation_body(
            BASE_MEDIA,"create",changes=CHANGES,
        )
        self.assertTrue(verify_project_operation(
            BASE_MEDIA,TWO_ROWS,"create",body=create,position=None,
        ))

    def test_delete_no_media_record_preserves_media_sibling(self):
        body=project_operation_body(TWO_ROWS,"delete",position=2)
        self.assertTrue(verify_project_operation(
            TWO_ROWS,BASE_MEDIA,"delete",body=body,position=2,
        ))
        corrupted=deepcopy(BASE_MEDIA)
        corrupted["project"]["formData"]["projects"][0]["img"]["fileId"]="unrelated"
        self.assertFalse(verify_project_operation(
            TWO_ROWS,corrupted,"delete",body=body,position=2,
        ))

    def test_hidden_media_type_none_is_rejected_before_update(self):
        bad=deepcopy(AFTER)
        bad["project"]["formData"]["projects"][0]["img"]["fileId"]="secret-existing-image"
        with self.assertRaises(UnsupportedWrite):
            project_operation_body(
                bad,"update",position=1,changes={"name":"Changed"},
            )
        for field in ("url","thumbnailUrl","thumbnailStatus"):
            bad=deepcopy(AFTER)
            bad["project"]["formData"]["projects"][0]["img"][field]="nonempty"
            with self.subTest(field=field),self.assertRaises(UnsupportedWrite):
                project_operation_body(
                    bad,"update",position=1,changes={"name":"Changed"},
                )


if __name__=="__main__":
    unittest.main()
