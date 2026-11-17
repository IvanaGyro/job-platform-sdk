"""Optional-dependency real HTTP wire test; only localhost and synthetic data."""
import asyncio
from email.parser import BytesParser
from email.policy import default
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from job_platforms.providers.tw104.http_transport import CurlCffiTransport
from job_platforms.providers.tw104.transport import BrowserUpload

HAS_CURL = importlib.util.find_spec("curl_cffi") is not None


class Recorder(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.records.append((self.headers.get("Content-Type", ""), raw,
                                    self.headers.get("104-profile-ver", "")))
        answer = b'{"data":{"accepted":true}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer)))
        self.send_header("104-profile-ver", "synthetic-new-version")
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, fmt, *args):
        pass


@unittest.skipUnless(HAS_CURL, "curl_cffi optional extra not installed")
class CurlWireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from curl_cffi.requests import AsyncSession
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        self.http.records = []
        self.thread = Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        session = AsyncSession(impersonate="chrome146", trust_env=False)
        self.transport = CurlCffiTransport(session, allow_writes=True)
        self.transport.ORIGIN = "http://127.0.0.1:" + str(self.http.server_port)
        self.transport._profile_version = "synthetic-prev-version"

    async def asyncTearDown(self):
        await self.transport.aclose()
        self.http.shutdown()
        await asyncio.to_thread(self.thread.join, 3)
        self.http.server_close()

    def parse_multipart(self):
        self.assertEqual(len(self.http.records), 1)
        ctype, body, version = self.http.records[0]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="), ctype)
        self.assertEqual(version, "synthetic-prev-version")
        data = b"MIME-Version: 1.0\r\nContent-Type: "+ctype.encode()+b"\r\n\r\n"+body
        message = BytesParser(policy=default).parsebytes(data)
        return {part.get_param("name", header="Content-Disposition"):
                (part.get_filename(), part.get_payload(decode=True))
                for part in message.iter_parts()}

    async def test_multipart_with_file_and_text_field(self):
        content = b"%PDF-1.4\n%synthetic\n%%EOF\n"
        response = await self.transport.request(
            "POST", "/profile/ajax/resumeByBlock/portfolio",
            multipart_fields={"blockValueList[portfolio][attachType]": "1"},
            multipart_upload=BrowserUpload("attachment", "synthetic.pdf",
                                          "application/pdf", content),
        )
        self.assertEqual(response.data["data"]["accepted"], True)
        self.assertEqual(self.transport._profile_version, "synthetic-new-version")
        parts = self.parse_multipart()
        self.assertEqual(parts["blockValueList[portfolio][attachType]"],
                         (None, b"1"))
        self.assertEqual(parts["attachment"], ("synthetic.pdf", content))

    async def test_multipart_text_only_link(self):
        await self.transport.request(
            "POST", "/profile/ajax/resumeByBlock/portfolio",
            multipart_fields={"blockValueList[portfolio][attach][url]":
                              "https://example.invalid/a?x=1&y=2"},
        )
        parts = self.parse_multipart()
        self.assertEqual(parts["blockValueList[portfolio][attach][url]"],
                         (None, b"https://example.invalid/a?x=1&y=2"))


if __name__ == "__main__":
    unittest.main()
