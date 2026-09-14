"""Small deterministic parity checks through the compatibility adapters."""

import unittest

from .legacy_adapter import load_legacy
from .revamped_adapter import load_revamped


class PureCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = load_legacy()
        cls.revamped = load_revamped()

    def test_validation_cases_have_matching_acceptance(self):
        values = ["Default", "Profile 1", "profile_0001", "", "..", "CON", "a/b"]
        for value in values:
            with self.subTest(value=value):
                legacy_result = self.outcome(self.legacy.validate_profile_id, value)
                revamped_result = self.outcome(self.revamped["core"].validate_profile_id, value)
                self.assertEqual(legacy_result[0], revamped_result[0])

    def test_environment_and_proxy_launch_policy_matches(self):
        records = [
            {},
            {"environment_preset": "mobile"},
            {"environment_preset": "custom", "environment_config": {
                "width": 1200, "height": 800, "scale_factor": 1.5,
                "language": "en-US", "mobile_mode": True, "touch_mode": False,
            }},
            {"proxy_enabled": False},
            {"proxy_enabled": True, "proxy_scheme": "socks5", "proxy_host": "2001:db8::1", "proxy_port": 1080},
        ]
        for record in records:
            with self.subTest(record=record):
                self.assertEqual(
                    self.legacy.effective_environment(record),
                    self.revamped["environment"].effective_environment(record),
                )
                self.assertEqual(
                    self.legacy.environment_launch_arguments(record),
                    self.revamped["environment"].environment_launch_arguments(record),
                )
                self.assertEqual(
                    self.legacy.effective_proxy(record),
                    self.revamped["proxy"].effective_proxy(record),
                )
                self.assertEqual(
                    self.legacy.proxy_launch_arguments(record),
                    self.revamped["proxy"].proxy_launch_arguments(record),
                )

    @staticmethod
    def outcome(function, value):
        try:
            return ("value", function(value))
        except Exception as error:
            return ("error", type(error).__name__)


if __name__ == "__main__":
    unittest.main()
