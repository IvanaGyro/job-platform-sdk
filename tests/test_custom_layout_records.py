"""Synthetic CLASSIC/BANNER CUSTOM CRUD; no account or network access."""
import asyncio
from copy import deepcopy
import unittest
from job_platforms.core.errors import ConflictError, UnsupportedWrite, VerificationError
from job_platforms.providers.tw104.client import Resume104Client
from job_platforms.providers.tw104.custom_layout_records import (
    layout_form, layout_operation_body, verify_layout_mutation,
)

OPTIONS = {"optionsCustomTheme": [{"value": 1}, {"value": 2}, {"value": 3}]}
CONTENT = {
    "duration": {"startYear": "", "startMonth": 0, "endYear": "", "endMonth": 0},
    "isInProgress": False,
    "introduction_html": "<p>Synthetic <strong>content</strong></p>",
    "url": "", "media": {"type": 0},
}
BASE = {"resume": {"vno": "synthetic"}, "resumeTimestamp": 100,
        "custom3": {"formData": {"sentinel": "unchanged-other-slot"}}}


def native_form(body):
    value = deepcopy(body["blockValueList"]["custom"])
    row = value["custom"]["content"][0]
    for field in ("startMonth", "endMonth"):
        if row["duration"][field] == "":
            row["duration"][field] = {}
    if row["isInProgress"] == 0:
        row["isInProgress"] = []
    row["file"] = [{"type": 0, "fileId": "", "thumbnailStatus": ""}]
    value["themeChoose"]["selectedTheme"] = {
        "value": value["themeChoose"]["selectedTheme"], "text": "Synthetic theme"
    }
    return value


class Transport:
    def __init__(self, owner, lost=False):
        self.owner, self.lost, self.calls = owner, lost, []

    async def get_json(self, path):
        assert path == "/profile/ajax/options"
        return {"data": deepcopy(OPTIONS)}

    async def request(self, method, path, *, params, json_data):
        assert path == "/profile/ajax/resumeByBlock/custom"
        assert params == {"vno": "synthetic"}
        self.calls.append((method, deepcopy(json_data)))
        if method == "DELETE":
            assert json_data["blockValueList"]["custom"]["custom"]["sort"] == [1]
            del self.owner.doc["custom1"]
        else:
            self.owner.doc["custom1"] = {"formData": native_form(json_data)}
        self.owner.doc["resumeTimestamp"] += 1
        if self.lost:
            raise VerificationError("Synthetic response lost after commit")
        return {"data": {}}


class Client(Resume104Client):
    def __init__(self, doc=BASE, *, lost=False):
        self.doc = deepcopy(doc)
        self.transport = Transport(self, lost)
        self._write_lock = asyncio.Lock()

    async def get_resume(self, resume_id):
        assert resume_id == "synthetic"
        return deepcopy(self.doc)


class CustomLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_classic_and_banner_create_update_delete(self):
        for theme, theme_name in ((1, "CLASSIC"), (2, "BANNER")):
            with self.subTest(theme=theme):
                c = Client()
                result = await c.mutate_custom_layout(
                    "synthetic", "create", slot=1, theme=theme,
                    name="Synthetic layout", content=deepcopy(CONTENT),
                    expected_timestamp=100,
                )
                self.assertEqual(result["theme"], theme_name)
                self.assertTrue(result["verified"])
                self.assertEqual(layout_form(c.doc, slot=1)["content"], CONTENT)
                update = await c.mutate_custom_layout(
                    "synthetic", "update", slot=1, name="Renamed layout",
                    expected_timestamp=101,
                )
                self.assertTrue(update["verified"])
                changed = deepcopy(CONTENT)
                changed["introduction_html"] = "<p>Synthetic replacement</p>"
                changed["duration"]["startYear"] = "2024"
                changed["duration"]["startMonth"] = 2
                await c.mutate_custom_layout(
                    "synthetic", "update", slot=1, content=changed,
                    expected_timestamp=102,
                )
                self.assertEqual(layout_form(c.doc, slot=1)["content"], changed)
                deleted = await c.mutate_custom_layout(
                    "synthetic", "delete", slot=1, expected_timestamp=103,
                )
                self.assertTrue(deleted["verified"])
                self.assertEqual(c.doc["custom3"], BASE["custom3"])
                self.assertNotIn("custom1", c.doc)
                self.assertEqual([item[0] for item in c.transport.calls],
                                 ["POST", "PUT", "PUT", "DELETE"])

    def test_strict_record_content_and_sibling_preservation(self):
        body = layout_operation_body(
            BASE, "create", slot=1, theme=1, name="Synthetic layout",
            content=CONTENT, options=OPTIONS,
        )
        after = deepcopy(BASE)
        after["custom1"] = {"formData": native_form(body)}
        self.assertTrue(verify_layout_mutation(BASE, after, "create", slot=1, body=body))
        after["custom3"]["formData"]["sentinel"] = "clobbered"
        self.assertFalse(verify_layout_mutation(BASE, after, "create", slot=1, body=body))
        after = deepcopy(BASE)
        after["custom1"] = {"formData": native_form(body)}
        after["custom1"]["formData"]["custom"]["content"][0]["introduction"] = "Wrong"
        self.assertFalse(verify_layout_mutation(BASE, after, "create", slot=1, body=body))

    async def test_bad_theme_media_html_and_occupied_slot_fail_before_write(self):
        for theme in (3, 4, 5, True, 0):
            with self.subTest(theme=theme):
                c = Client()
                with self.assertRaises(UnsupportedWrite):
                    await c.mutate_custom_layout(
                        "synthetic", "create", slot=1,
                        expected_timestamp=100, theme=theme,
                        name="Synthetic", content=CONTENT,
                    )
                self.assertEqual(c.transport.calls, [])
        for bad in (
            {**CONTENT, "media": {"type": 1}},
            {**CONTENT, "introduction_html": "<script>unsafe</script>"},
            {**CONTENT, "url": "javascript:alert(1)"},
            {**CONTENT, "duration": {"startYear": ""}},
        ):
            with self.subTest(bad=bad):
                c = Client()
                with self.assertRaises(UnsupportedWrite):
                    await c.mutate_custom_layout(
                        "synthetic", "create", slot=1,
                        expected_timestamp=100, theme=1,
                        name="Synthetic", content=bad,
                    )
                self.assertEqual(c.transport.calls, [])
        occupied = deepcopy(BASE)
        occupied["custom1"] = {"formData": {"different": "custom theme"}}
        c = Client(occupied)
        with self.assertRaises(UnsupportedWrite):
            await c.mutate_custom_layout(
                "synthetic", "create", slot=1, expected_timestamp=100,
                theme=2, name="Collision", content=CONTENT,
            )
        self.assertEqual(c.transport.calls, [])

    async def test_update_delete_reject_unknown_media_or_other_theme(self):
        body = layout_operation_body(
            BASE, "create", slot=1, theme=1, name="Synthetic",
            content=CONTENT, options=OPTIONS,
        )
        created = deepcopy(BASE)
        created["custom1"] = {"formData": native_form(body)}
        for modification in ("media", "theme", "metadata"):
            bad = deepcopy(created)
            if modification == "media":
                bad["custom1"]["formData"]["custom"]["content"][0]["file"][0]["fileId"] = "stored-asset"
            elif modification == "theme":
                bad["custom1"]["formData"]["themeChoose"]["selectedTheme"]["value"] = 5
            else:
                bad["custom1"]["formData"]["custom"]["content"][0]["other"] = "private"
            for action in ("update", "delete"):
                with self.subTest(action=action, modification=modification):
                    c = Client(bad)
                    with self.assertRaises(UnsupportedWrite):
                        await c.mutate_custom_layout(
                            "synthetic", action, slot=1, expected_timestamp=100,
                            **({"name": "Change"} if action == "update" else {}),
                        )
                    self.assertEqual(c.transport.calls, [])

    def test_ongoing_status_cannot_mask_unrestored_end_dates(self):
        body = layout_operation_body(
            BASE, "create", slot=1, theme=1, name="Synthetic",
            content=CONTENT, options=OPTIONS,
        )
        after = deepcopy(BASE)
        after["custom1"] = {"formData": native_form(body)}
        row = after["custom1"]["formData"]["custom"]["content"][0]
        row["isInProgress"] = 1
        row["duration"]["endYear"] = "2025"
        self.assertFalse(verify_layout_mutation(
            BASE, after, "create", slot=1, body=body,
        ))
        with self.assertRaises(UnsupportedWrite):
            layout_form(after, slot=1)

    async def test_stale_and_ambiguous_write_not_retried(self):
        c = Client()
        with self.assertRaises(ConflictError):
            await c.mutate_custom_layout(
                "synthetic", "create", slot=1, expected_timestamp=99,
                name="Synthetic", theme=1, content=CONTENT,
            )
        self.assertEqual(c.transport.calls, [])
        c = Client(lost=True)
        with self.assertRaises(VerificationError):
            await c.mutate_custom_layout(
                "synthetic", "create", slot=1, expected_timestamp=100,
                name="Synthetic", theme=1, content=CONTENT,
            )
        self.assertEqual([x[0] for x in c.transport.calls], ["POST"])


if __name__ == "__main__":
    unittest.main()
