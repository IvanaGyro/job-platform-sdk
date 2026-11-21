"""Configuration-only tests; do not read real credentials or use the network."""
import os
import unittest
from unittest.mock import patch

from job_platforms.providers.tw104.auth import AuthConfig


class AuthPriorityTests(unittest.TestCase):
    ENV = {
        "JOB_PLATFORM_104_CREDENTIALS_FILE": "/synthetic/credentials",
        "JOB_PLATFORM_104_PROXY_FILE": "/synthetic/proxies",
    }

    def test_default_priority_remains_unchanged(self):
        with patch.dict(os.environ, self.ENV, clear=True):
            cfg = AuthConfig.from_env()
        self.assertEqual(cfg.proxy_priority, (4, 2, 5, 1, 3, 6, 7, 8, 9, 10))

    def test_limit_login_to_one_known_proxy(self):
        with patch.dict(os.environ, {
            **self.ENV, "JOB_PLATFORM_104_PROXY_PRIORITY": "4",
        }, clear=True):
            cfg = AuthConfig.from_env()
        self.assertEqual(cfg.proxy_priority, (4,))

    def test_invalid_priority_fails_before_any_browser(self):
        for value in ("", "0", "4,4", "4,", "4,abc", "-1", "101", "04", "1 2"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {
                    **self.ENV, "JOB_PLATFORM_104_PROXY_PRIORITY": value,
                }, clear=True):
                    with self.assertRaises(ValueError):
                        AuthConfig.from_env()


if __name__ == "__main__":
    unittest.main()
