"""R3 environment/proxy parity and safety tests using pure synthetic values."""

import json
import subprocess
import sys
import unittest

from compatibility.legacy_adapter import load_legacy
from revamped import environment, proxy


class R3PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = load_legacy()

    def test_environment_normalization_matches_legacy(self):
        values = [
            "default", "desktop", "Mobile", " custom ", "unknown", None,
        ]
        configs = [
            None,
            {},
            {"width": "1024", "height": 768, "scale_factor": "1.25", "locale": "vi_VN", "timezone": "UTC", "mobile": True},
            {"width": -1, "height": "bad", "scale_factor": "nan", "timezone": "Not/A_Timezone"},
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    environment.normalize_environment_preset(value),
                    self.legacy.normalize_environment_preset(value),
                )
        for config in configs:
            with self.subTest(config=config):
                self.assertEqual(
                    environment.normalize_environment_config(config),
                    self.legacy.normalize_environment_config(config),
                )

    def test_environment_effective_and_launch_arguments_match_legacy(self):
        records = [
            {},
            {"environment_preset": "default"},
            {"environment_preset": "mobile"},
            {"environment_preset": "custom", "environment_config": {"width": 1200, "height": 800, "scale_factor": 1.5, "language": "en-US", "mobile_mode": True, "touch_mode": False, "timezone": "UTC"}},
            {"environment_preset": "custom", "environment_config": ["broken"]},
        ]
        for record in records:
            with self.subTest(record=record):
                self.assertEqual(environment.effective_environment(record), self.legacy.effective_environment(record))
                self.assertEqual(environment.environment_launch_arguments(record), self.legacy.environment_launch_arguments(record))

    def test_environment_editor_and_timezone_contract_match(self):
        for preset, config in (("desktop", None), ("mobile", None), ("custom", {"width": 800, "height": 600, "timezone": "UTC"})):
            with self.subTest(preset=preset):
                self.assertEqual(environment.environment_editor_state(preset, config), self.legacy.environment_editor_state(preset, config))
        self.assertEqual(environment.normalize_timezone("UTC"), "UTC")
        self.assertIsNone(environment.normalize_timezone("Not/A_Timezone"))
        self.assertEqual(environment.environment_launch_arguments({"environment_preset": "custom", "environment_config": {"timezone": "UTC"}}), [])

    def test_proxy_normalization_and_launch_arguments_match_legacy(self):
        values = [
            ("http", "proxy.example", 8080),
            (" HTTPS ", " Proxy.Example. ", "443"),
            ("socks5", "[2001:db8::1]", "1081"),
            ("ftp", "proxy.example", 21),
            ("http", "user:pass@proxy.example", 80),
        ]
        for args in values:
            with self.subTest(args=args):
                self.assertEqual(proxy.normalize_proxy_config(*args), self.legacy.normalize_proxy_config(*args))
        records = [
            {"proxy_enabled": False},
            {"proxy_enabled": True, "proxy_scheme": "https", "proxy_host": "proxy.example", "proxy_port": 443},
            {"proxy_enabled": True, "proxy_scheme": "socks5", "proxy_host": "2001:db8::1", "proxy_port": 1080},
            {"proxy_enabled": True, "proxy_scheme": "unknown", "proxy_host": "bad host", "proxy_port": []},
        ]
        for record in records:
            with self.subTest(record=record):
                self.assertEqual(proxy.effective_proxy(record), self.legacy.effective_proxy(record))
                self.assertEqual(proxy.proxy_launch_arguments(record), self.legacy.proxy_launch_arguments(record))

    def test_proxy_parser_boundary_matches_without_logging_or_network(self):
        endpoints = [
            "proxy.example:8080",
            "https://proxy.example:8443",
            "[2001:db8::1]:1080",
        ]
        for value in endpoints:
            with self.subTest(endpoint=value):
                self.assertEqual(proxy.parse_proxy_string(value), self.legacy.parse_proxy_string(value))
        auth = f"{'u' * 5}:{'p' * 7}"
        for value in (f"https://{auth}@proxy.example:8443", f"proxy.example:8080:{auth}"):
            with self.subTest(authenticated_input=True):
                with self.assertRaises(proxy.ProxyValidationError) as modern_error:
                    proxy.parse_proxy_string(value)
                with self.assertRaises(self.legacy.ProxyValidationError) as legacy_error:
                    self.legacy.parse_proxy_string(value)
                self.assertNotIn(value, str(modern_error.exception))
                self.assertNotIn(value, str(legacy_error.exception))
        parsed = proxy.parse_proxy_string("https://proxy.example:8443")
        self.assertEqual(set(parsed), {"scheme", "host", "port"})
        self.assertIsNone(proxy.normalize_proxy_config("http", "userinfo@proxy.example", 80))

    def test_compare_script_reports_r3_categories(self):
        result = subprocess.run(
            [sys.executable, "-B", "scripts/compare_legacy_revamped.py"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ENVIRONMENT: PASS", result.stdout)
        self.assertIn("PROXY: PASS", result.stdout)
        self.assertIn("METADATA: PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
