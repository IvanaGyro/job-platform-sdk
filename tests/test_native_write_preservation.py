"""All 104 native writers must detect collateral edits, not target-only success.

A synthetic transport applies the *correct* target change and silently
corrupts an otherwise untouched CUSTOM slot. A writer must not report
verified=True or issue a second remote mutation to recover from this.
"""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch

from job_platforms.core.errors import VerificationError
from job_platforms.providers.tw104.patch_verification import (
    verify_untouched_blocks,
)
from test_skill_records import Client as SkillClient
from test_education_records import Client as EducationClient
from test_experience_records import Client as ExperienceClient
from test_referrer_records import Client as ReferrerClient, POPULATED as REFERRER_FORM
from test_project_records import Client as ProjectClient, POPULATED as PROJECT_FORM
from test_language_records import Client as LanguageClient
from test_bio_actions import Client as BioClient, NEW as BIO_CHANGES
from test_certificate_block_actions import Client as CertificateClient
from test_custom_layout_records import Client as LayoutClient, CONTENT as LAYOUT_CONTENT
from test_custom_text_live import Client as TextClient
from test_layout_theme import Client as ThemeClient
from test_record_sort import Client as SortClient
from test_portfolio_records import (
    Client as PortfolioClient, LINK as PORTFOLIO_LINK,
    POPULATED as PORTFOLIO_BASE,
)
from test_portfolio_binary_upload import (
    FileClient as PortfolioFileClient, PDF as SYNTHETIC_PDF,
)


PRESERVED = {"formData": {"synthetic_marker": "untouched"}}
BROKEN = {"formData": {"synthetic_marker": "corrupted by mock upstream"}}


def poison_native_request(client, method="request"):
    client.doc["custom6"] = deepcopy(PRESERVED)
    original = getattr(client.transport, method)

    async def injected(*args, **kwargs):
        result = await original(*args, **kwargs)
        client.doc["custom6"] = deepcopy(BROKEN)
        return result

    setattr(client.transport, method, injected)
    return client


class NativeWriterPreservationTests(unittest.IsolatedAsyncioTestCase):
    def test_sibling_allowlist_strict_and_file_exception(self):
        before = {"bio": {"formData": {"bio": {"chi": "before"}}},
                  "custom2": deepcopy(PRESERVED)}
        after = deepcopy(before)
        after["bio"]["formData"]["bio"]["chi"] = "after"
        self.assertTrue(verify_untouched_blocks(before, after, changed="bio"))
        self.assertFalse(verify_untouched_blocks(before, after, changed="under18"))
        self.assertFalse(verify_untouched_blocks(before, after, changed="custom"))
        after["custom2"] = deepcopy(BROKEN)
        self.assertFalse(verify_untouched_blocks(before, after, changed="bio"))
        for invalid in ("not_a_native_block", (), ("bio", "bio"), True):
            with self.subTest(invalid=invalid):
                self.assertFalse(verify_untouched_blocks(before, after, changed=invalid))

    async def test_record_writers_cannot_approve_collateral_custom_damage(self):
        specs = [
            ("skill", SkillClient(), "mutate_skill", ("synthetic", "update"),
             {"position": 1, "changes": {"desc": "new"}, "expected_timestamp": 123}),
            ("education", EducationClient(), "mutate_education", ("synthetic", "update"),
             {"position": 1, "changes": {"name": "new school"}, "expected_timestamp": 100}),
            ("experience", ExperienceClient(), "mutate_experience", ("synthetic", "update"),
             {"position": 1, "changes": {"jobName": "new role"}, "expected_timestamp": 100}),
            ("referrer", ReferrerClient(doc=REFERRER_FORM), "mutate_referrer",
             ("synthetic", "update"), {"position": 1, "changes": {"position": "new role"},
                                        "expected_timestamp": 100}),
            ("project", ProjectClient(doc=PROJECT_FORM), "mutate_project", ("synthetic", "update"),
             {"position": 1, "changes": {"name": "new project"}, "expected_timestamp": 100}),
            ("language", LanguageClient(), "mutate_language", ("synthetic", "local", "update"),
             {"position": 1, "changes": {"level": {"text": "精通", "value": 2}},
              "expected_timestamp": 100}),
        ]
        with patch("job_platforms.providers.tw104.client.asyncio.sleep", new=AsyncMock()):
            for name, client, operation, args, kwargs in specs:
                with self.subTest(section=name):
                    poison_native_request(client)
                    with self.assertRaises(VerificationError):
                        await getattr(client, operation)(*args, **kwargs)
                    self.assertEqual(len(client.transport.calls), 1)
                    self.assertEqual(client.doc["custom6"], BROKEN)

    async def test_rotating_file_tokens_do_not_block_unrelated_native_skill_write(self):
        client = SkillClient()
        client.doc["portfolio"] = deepcopy(PORTFOLIO_BASE["portfolio"])
        real_get = client.get_resume
        reads = 0

        async def with_rotating_opaque_file_access_tokens(version):
            nonlocal reads
            reads += 1
            result = await real_get(version)
            records = result["portfolio"]["formData"]["portfolios"]
            for row in records:
                for key in ("fileId", "thumbnailFileId", "src", "url"):
                    row["attach"][key] = f"access-{reads}-{key}-{row['sort']}"
            return result

        client.get_resume = with_rotating_opaque_file_access_tokens
        response = await client.mutate_skill(
            "synthetic", "update", position=1,
            changes={"desc": "Updated with rotating file tokens"},
            expected_timestamp=123,
        )
        self.assertTrue(response["verified"])
        self.assertEqual(len(client.transport.calls), 1)
        self.assertEqual(reads, 2)

    async def test_link_destination_change_blocks_unrelated_skill_write(self):
        client = SkillClient()
        doc = deepcopy(PORTFOLIO_BASE["portfolio"])
        doc["formData"]["portfolios"][0]["attachType"] = {
            "text": "Link", "value": 2,
        }
        doc["formData"]["portfolios"][0]["attach"]["url"] =             "https://example.invalid/original"
        client.doc["portfolio"] = doc
        real_request = client.transport.request

        async def modify_link_destination(*args, **kwargs):
            result = await real_request(*args, **kwargs)
            client.doc["portfolio"]["formData"]["portfolios"][0]["attach"]["url"] =                 "https://example.invalid/unexpected-change"
            return result

        client.transport.request = modify_link_destination
        with patch("job_platforms.providers.tw104.client.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(VerificationError):
                await client.mutate_skill(
                    "synthetic", "update", position=1,
                    changes={"desc": "Updated with a damaged link"},
                    expected_timestamp=123,
                )
        self.assertEqual(len(client.transport.calls), 1)

    async def test_other_native_writers_preserve_unrelated_blocks(self):
        specs = [
            ("bio", BioClient(), "mutate_bio", ("synthetic", "create"),
             {"changes": BIO_CHANGES, "expected_timestamp": 100}, "request"),
            ("certificate", CertificateClient(), "mutate_certificate_block",
             ("synthetic", "initialize"), {"others": "Synthetic", "expected_timestamp": 100},
             "request"),
            ("custom-layout", LayoutClient(), "mutate_custom_layout",
             ("synthetic", "create"), {"slot": 1, "theme": 1,
             "name": "Synthetic", "content": LAYOUT_CONTENT, "expected_timestamp": 100}, "request"),
            ("custom-text", TextClient(), "mutate_custom_text", ("synthetic", "create"),
             {"slot": 1, "name": "Synthetic", "introduction_html": "<p>Test</p>",
              "expected_timestamp": 100}, "request"),
            ("theme", ThemeClient(), "set_theme", ("synthetic", "skill", 2),
             {"expected_timestamp": 42}, "put_json"),
            ("sort", SortClient(), "sort_records", ("synthetic", "education", 1, 2),
             {"expected_timestamp": 100}, "put_json"),
            ("portfolio-link", PortfolioClient(), "mutate_portfolio",
             ("synthetic", "create"),
             {"expected_timestamp": 100, "changes": PORTFOLIO_LINK}, "request"),
            ("portfolio-file", PortfolioFileClient(), "upload_portfolio_file",
             ("synthetic",), {"expected_timestamp": 100,
             "name": "Synthetic upload item", "attach_name": "synthetic.pdf",
             "filename": "synthetic.pdf", "content_type": "application/pdf",
             "content": SYNTHETIC_PDF}, "request"),
        ]
        with patch("job_platforms.providers.tw104.client.asyncio.sleep", new=AsyncMock()):
            for name, client, operation, args, kwargs, network_method in specs:
                with self.subTest(section=name):
                    poison_native_request(client, network_method)
                    with self.assertRaises(VerificationError):
                        await getattr(client, operation)(*args, **kwargs)
                    self.assertEqual(len(client.transport.calls), 1)
                    self.assertEqual(client.doc["custom6"], BROKEN)


if __name__ == "__main__":
    unittest.main()
