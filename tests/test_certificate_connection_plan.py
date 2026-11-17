"""Offline certification association mapping from 104's Vuex 779c."""
from contextlib import redirect_stdout
from pathlib import Path
import io
import json
import tempfile
import unittest

from job_platforms.cli import _parser, _run
from job_platforms.core.errors import UnsupportedWrite
from job_platforms.providers.tw104.certificate_connection_contract import (
    certificate_connect_plan, certificate_disconnect_plan,
    certificate_other_text_disconnect_plan,
)


class CertificateConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def cli(self, args):
        parsed = _parser().parse_args(["certificate-link-plan", *args])
        with redirect_stdout(io.StringIO()) as capture:
            await _run(parsed)
        return json.loads(capture.getvalue())

    def test_source_action_and_body(self):
        self.assertEqual(certificate_connect_plan([101,102]), {
            "frontend_action":"api/certificationConnect/put",
            "method":"PUT",
            "body":{"certIds":[101,102]},
            "remote_write_enabled":False,
        })
        self.assertEqual(certificate_disconnect_plan(101), {
            "frontend_action":"api/certificationConnect/delete",
            "method":"DELETE", "record_id":101,
            "body":None, "remote_write_enabled":False,
        })
        self.assertEqual(certificate_other_text_disconnect_plan(), {
            "frontend_action":"api/certificationConnect/deleteOther",
            "method":"DELETE","body":None,
            "remote_write_enabled":False,
        })

    def test_invalid_ids_never_generate_action(self):
        for value in ([], [0], [-1], [True], ["1"], [1,1],
                      [1]*31, "bad", None, [1,1.5]):
            with self.subTest(value=value), self.assertRaises(UnsupportedWrite):
                certificate_connect_plan(value)
        for value in (-1, 0, True, "", "42", None):
            with self.subTest(value=value), self.assertRaises(UnsupportedWrite):
                certificate_disconnect_plan(value)

    async def test_cli_connect_disconnect_and_other_no_login(self):
        with tempfile.TemporaryDirectory() as folder:
            ids=Path(folder)/"synthetic-ids.json"
            ids.write_text(json.dumps([123,321]),encoding="utf-8")
            linked=await self.cli(["connect","--ids-file",str(ids)])
        self.assertFalse(linked["network_sent"])
        self.assertFalse(linked["remote_write_enabled"])
        self.assertEqual(linked["body"],{"certIds":[123,321]})
        single=await self.cli(["disconnect","--record-id","123"])
        self.assertEqual(single["record_id"],123)
        other=await self.cli(["disconnect-other"])
        self.assertEqual(
            other["frontend_action"],"api/certificationConnect/deleteOther"
        )
        for args in (
            ["connect"],
            ["disconnect"],
            ["disconnect-other","--record-id","2"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                await self.cli(args)


if __name__=="__main__":
    unittest.main()
