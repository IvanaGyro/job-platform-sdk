"""104-profile-ver handshake tests with synthetic response headers only."""
import unittest

from job_platforms.core.errors import UpstreamError, VerificationError
from job_platforms.providers.tw104.transport import BrowserTransport


class FakePage:
    url = "https://pda.104.com.tw/profile"

    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    async def evaluate(self, script, data):
        self.calls.append(data)
        return next(self.replies)


def reply(status=200, profile_version=None):
    return {
        "status": status,
        "content_type": "application/json",
        "data": {"data": {}},
        "profile_version": profile_version,
    }


class ProfileVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_refused_before_profile_version_initialized(self):
        page = FakePage([])
        transport = BrowserTransport(page)
        with self.assertRaises(VerificationError):
            await transport.put_json(
                "/profile/ajax/resumeByBlock/bio", {},
                params={"vno": "synthetic-version-no"},
            )
        self.assertEqual(page.calls, [])

    async def test_get_header_propagated_to_write_and_refreshed(self):
        page = FakePage([
            reply(profile_version="synthetic-profile-version-a"),
            reply(profile_version="synthetic-profile-version-b"),
            reply(profile_version="synthetic-profile-version-c"),
        ])
        transport = BrowserTransport(page)
        await transport.get_json("/profile/ajax/overview")
        body = {"blockValueList": {"bio": {"bio": {
            "chi": "synthetic-chinese", "eng": "synthetic-english",
        }}}}
        await transport.put_json(
            "/profile/ajax/resumeByBlock/bio", body,
            params={"vno": "synthetic-resume"},
        )
        await transport.put_json(
            "/profile/ajax/resumeByBlock/bio", body,
            params={"vno": "synthetic-resume"},
        )
        self.assertEqual(page.calls[0]["profile_version"], None)
        self.assertEqual(page.calls[1]["profile_version"], "synthetic-profile-version-a")
        self.assertEqual(page.calls[2]["profile_version"], "synthetic-profile-version-b")
        self.assertEqual(page.calls[1]["method"], "PUT")
        self.assertEqual(page.calls[1]["json"], body)
        self.assertEqual(
            page.calls[1]["path"],
            "/profile/ajax/resumeByBlock/bio?vno=synthetic-resume",
        )

    async def test_400_response_keeps_original_version_and_sanitizes_url(self):
        page = FakePage([
            reply(profile_version="synthetic-header"),
            reply(status=400),
        ])
        transport = BrowserTransport(page)
        await transport.get_json("/profile/ajax/overview")
        with self.assertRaises(UpstreamError) as caught:
            await transport.put_json(
                "/profile/ajax/resumeByBlock/bio",
                {"blockValueList": {"bio": {"bio": {"chi": "", "eng": ""}}}},
                params={"vno": "synthetic-version"},
            )
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(
            caught.exception.endpoint,
            "/profile/ajax/resumeByBlock/bio",
        )


if __name__ == "__main__":
    unittest.main()
