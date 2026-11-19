"""Exercise explicit 104-native CLI dispatch without any browser or private data."""
import argparse
import asyncio
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from job_platforms.cli import _parser, _run


class DummyClient:
    SECTIONS = ("bio", "info", "experience", "skill", "education")
    calls = []
    def __init__(self, _page):
        pass

    async def mutate_experience(self, version, action, **kwargs):
        self.calls.append(("experience", version, action, kwargs))
        return {"verified": True}

    async def mutate_certificate_block(self, version, action, **kwargs):
        self.calls.append(("certificate-block", version, action, kwargs))
        return {"verified": True}

    async def mutate_bio(self, version, action, **kwargs):
        self.calls.append(("bio-action", version, action, kwargs))
        return {"verified": True}

    async def mutate_project(self, version, action, **kwargs):
        self.calls.append(("project", version, action, kwargs))
        return {"verified": True}

    async def mutate_portfolio(self, version, action, **kwargs):
        self.calls.append(("portfolio", version, action, kwargs))
        return {"verified": True}

    async def mutate_referrer(self, version, action, **kwargs):
        self.calls.append(("referrer", version, action, kwargs))
        return {"verified": True}

    async def get_language_editor_options(self, version, kind):
        self.calls.append(("language-options", version, kind))
        return {"resume_id": version, "kind": kind, "remaining_capacity": 2,
                "persisted": False}

    async def mutate_language(self, version, kind, action, **kwargs):
        self.calls.append(("language", version, kind, action, kwargs))
        return {"verified": True}

    async def set_theme(self, version, section, value, **kwargs):
        self.calls.append(("theme", version, section, value, kwargs))
        return {"verified": True}

    async def sort_records(self, version, section, from_pos, to_pos, **kwargs):
        self.calls.append(("sort", version, section, from_pos, to_pos, kwargs))
        return {"verified": True}


class FakeBrowser:
    page = object()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False


class CLI104Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        DummyClient.calls = []
        self.patches = [
            patch("job_platforms.cli.AuthConfig.from_env", return_value=argparse.Namespace(headless=False)),
            patch("job_platforms.cli.FreshBrowserSession", return_value=FakeBrowser()),
            patch("job_platforms.cli.Resume104Client", DummyClient),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()

    async def execute(self, argv):
        args = _parser().parse_args(argv)
        with redirect_stdout(io.StringIO()) as captured:
            await _run(args)
        return json.loads(captured.getvalue())

    async def test_language_options_read_only_cli_dispatch(self):
        data = await self.execute(["language-options", "synthetic", "foreign"])
        self.assertEqual(DummyClient.calls, [("language-options", "synthetic", "foreign")])
        self.assertEqual(data["remaining_capacity"], 2)
        self.assertFalse(data["persisted"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _parser().parse_args(["language-options", "synthetic", "unknown"])

    async def test_experience_and_language_native_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "synthetic.json"
            file.write_text(json.dumps({"jobName": "Synthetic Engineer"}))
            await self.execute([
                "record", "synthetic", "experience", "update",
                "--position", "2", "--changes-file", str(file),
                "--if-match", "42", "--confirm", "experimental-record-write",
            ])
            self.assertEqual(DummyClient.calls[-1], (
                "experience", "synthetic", "update",
                {"changes": {"jobName": "Synthetic Engineer"}, "position": 2,
                 "expected_timestamp": "42"},
            ))
            await self.execute([
                "record", "synthetic", "language", "delete",
                "--kind", "foreign", "--position", "1",
                "--if-match", "42", "--confirm", "experimental-record-write",
            ])
            self.assertEqual(DummyClient.calls[-1][:4], (
                "language", "synthetic", "foreign", "delete",
            ))

    async def test_referrer_native_cli_dispatch(self):
        await self.execute([
            "record", "synthetic", "referrer", "delete", "--position", "2",
            "--if-match", "99", "--confirm", "experimental-record-write",
        ])
        self.assertEqual(DummyClient.calls[-1], (
            "referrer", "synthetic", "delete",
            {"expected_timestamp": "99", "changes": None, "position": 2}
        ))

    async def test_theme_and_sort_native_dispatch(self):
        await self.execute([
            "theme", "synthetic", "skill", "2",
            "--if-match", "41", "--confirm", "experimental-theme-write",
        ])
        await self.execute([
            "sort", "synthetic", "education", "1", "2",
            "--if-match", "41", "--confirm", "experimental-sort-write",
        ])
        self.assertEqual(DummyClient.calls[0], (
            "theme", "synthetic", "skill", 2, {"expected_timestamp": "41"}
        ))
        self.assertEqual(DummyClient.calls[1], (
            "sort", "synthetic", "education", 1, 2, {"expected_timestamp": "41"}
        ))

    async def test_language_adjacent_sort_native_cli_dispatch(self):
        await self.execute([
            "sort", "synthetic", "language", "1", "2",
            "--kind", "local", "--if-match", "41",
            "--confirm", "experimental-sort-write",
        ])
        self.assertEqual(DummyClient.calls[-1], (
            "sort", "synthetic", "language", 1, 2,
            {"expected_timestamp": "41", "kind": "local"},
        ))
        for argv in (
            ["sort", "synthetic", "language", "1", "2"],
            ["sort", "synthetic", "skill", "1", "2", "--kind", "local"],
        ):
            with self.assertRaises(ValueError):
                await self.execute(argv + [
                    "--if-match", "41", "--confirm", "experimental-sort-write",
                ])

    async def test_referrer_exactly_two_sort_cli(self):
        await self.execute([
            "sort", "synthetic", "referrer", "1", "2",
            "--if-match", "41", "--confirm", "experimental-sort-write",
        ])
        self.assertEqual(DummyClient.calls[-1], (
            "sort", "synthetic", "referrer", 1, 2,
            {"expected_timestamp": "41"},
        ))

    async def test_bio_create_and_clear_native_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "synthetic-bio.json"
            file.write_text(json.dumps({
                "chi": "<p>Synthetic</p>", "eng": "<p>Test</p>",
            }))
            await self.execute([
                "bio-action", "synthetic", "create", "--changes-file", str(file),
                "--if-match", "77", "--confirm", "experimental-bio-action-write",
            ])
            self.assertEqual(DummyClient.calls[-1], (
                "bio-action", "synthetic", "create",
                {"changes": {"chi": "<p>Synthetic</p>", "eng": "<p>Test</p>"},
                 "expected_timestamp": "77"},
            ))
        await self.execute([
            "bio-action", "synthetic", "clear",
            "--if-match", "78", "--confirm", "experimental-bio-action-write",
        ])
        self.assertEqual(DummyClient.calls[-1], (
            "bio-action", "synthetic", "clear",
            {"changes": None, "expected_timestamp": "78"},
        ))
        for action, extra in (("create", []), ("clear", ["--changes-file", "unused"])):
            with self.assertRaises(ValueError):
                await self.execute([
                    "bio-action", "synthetic", action, *extra,
                    "--if-match", "78", "--confirm", "experimental-bio-action-write",
                ])

    async def test_project_and_portfolio_cli_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "synthetic-project.json"
            file.write_text(json.dumps({
                "name": "Synthetic Project", "introduction": "<p>Test</p>",
            }), encoding="utf-8")
            await self.execute([
                "record", "synthetic", "project", "update", "--position", "1",
                "--changes-file", str(file),
                "--if-match", "100", "--confirm", "experimental-record-write",
            ])
            self.assertEqual(DummyClient.calls[-1], (
                "project", "synthetic", "update",
                {"expected_timestamp": "100", "changes": {
                    "name": "Synthetic Project", "introduction": "<p>Test</p>"
                }, "position": 1},
            ))
        with tempfile.TemporaryDirectory() as folder:
            link = Path(folder) / "synthetic-link.json"
            fields = {
                "name": "Synthetic Portfolio Link",
                "attachName": "Example",
                "url": "https://example.invalid",
            }
            link.write_text(json.dumps(fields), encoding="utf-8")
            await self.execute([
                "record", "synthetic", "portfolio", "create",
                "--changes-file", str(link),
                "--if-match", "100", "--confirm", "experimental-record-write",
            ])
            self.assertEqual(DummyClient.calls[-1], (
                "portfolio", "synthetic", "create",
                {"expected_timestamp": "100", "changes": fields, "position": None},
            ))
        await self.execute([
            "record", "synthetic", "portfolio", "delete", "--position", "2",
            "--if-match", "101", "--confirm", "experimental-record-write",
        ])
        self.assertEqual(DummyClient.calls[-1], (
            "portfolio", "synthetic", "delete",
            {"expected_timestamp": "101", "changes": None, "position": 2},
        ))
        await self.execute([
            "sort", "synthetic", "portfolio", "1", "2",
            "--if-match", "102", "--confirm", "experimental-sort-write",
        ])
        self.assertEqual(DummyClient.calls[-1], (
            "sort", "synthetic", "portfolio", 1, 2,
            {"expected_timestamp": "102"},
        ))
        with self.assertRaises(ValueError):
            await self.execute([
                 "record", "synthetic", "portfolio", "create", "--if-match", "99",
                "--confirm", "experimental-record-write",
            ])

    async def test_native_certificate_block_initialization_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "synthetic-certification.txt"
            source.write_text("Synthetic certificate", encoding="utf-8")
            await self.execute([
                "certificate-block", "synthetic", "initialize",
                "--others-file", str(source), "--if-match", "100",
                "--confirm", "experimental-certificate-write",
            ])
            self.assertEqual(DummyClient.calls[-1], (
                "certificate-block", "synthetic", "initialize",
                {"others": "Synthetic certificate",
                 "expected_timestamp": "100"},
            ))
        await self.execute([
            "certificate-block", "synthetic", "clear",
            "--if-match", "101",
            "--confirm", "experimental-certificate-write",
        ])
        self.assertEqual(DummyClient.calls[-1], (
            "certificate-block", "synthetic", "clear",
            {"others": None, "expected_timestamp": "101"},
        ))
        for argv in (
            ["certificate-block", "synthetic", "initialize"],
            ["certificate-block", "synthetic", "clear", "--others-file", "invalid"],
        ):
            with self.assertRaises(ValueError):
                await self.execute(argv + [
                    "--if-match", "101",
                    "--confirm", "experimental-certificate-write",
                ])

    async def test_invalid_record_combinations_do_not_write(self):
        invalid = (
            ["record", "synthetic", "language", "delete", "--position", "1"],
            ["record", "synthetic", "experience", "delete", "--kind", "local", "--position", "1"],
            ["record", "synthetic", "skill", "create"],
            ["record", "synthetic", "education", "delete", "--changes-file", "unused", "--position", "1"],
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                await self.execute(values + [
                    "--if-match", "42", "--confirm", "experimental-record-write",
                ])
        self.assertEqual(DummyClient.calls, [])


if __name__ == "__main__":
    unittest.main()
