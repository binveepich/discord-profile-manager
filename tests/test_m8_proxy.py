"""M8 optional per-profile proxy tests using disposable synthetic profiles."""

import inspect
import json
import unittest
from unittest.mock import Mock, patch

import test_m1_runtime as m1
from test_m6_gui import FakeTree, FakeVar


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    setUp = m1.RuntimeTests.setUp
    cleanup_workspace = m1.RuntimeTests.cleanup_workspace
    make_runtime = m1.RuntimeTests.make_runtime
    make_profiles = m1.RuntimeTests.make_profiles

    def test_existing_profile_defaults_to_proxy_off(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Proxy default")

        self.assertEqual(profiles.get_proxy(profile_id), {
            "enabled": False, "scheme": None, "host": None, "port": None,
        })
        record = profiles.get_profile_metadata()[0]
        self.assertFalse(record["proxy_enabled"])
        self.assertEqual(self.manager.proxy_launch_arguments(record), [])

    def test_legacy_proxy_enabled_false_remains_compatible(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Legacy proxy off")
        catalog = json.loads(self.manager.PROFILES_JSON.read_text(encoding="utf-8"))
        record = catalog["profiles"][0]
        record.update({
            "proxy_enabled": False,
            "proxy_scheme": "not-a-scheme",
            "proxy_host": "not a host",
            "proxy_port": "not-a-port",
        })
        self.manager.PROFILES_JSON.write_text(json.dumps(catalog), encoding="utf-8")

        restarted = self.manager.ProfileManager()
        self.assertFalse(restarted.get_proxy(profile_id)["enabled"])
        self.assertEqual(self.manager.proxy_launch_arguments(
            restarted.get_profile_metadata()[0]
        ), [])

    def test_proxy_off_adds_no_chromium_proxy_argument(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("No proxy launch")

        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id))
        command = self.popen.call_args.args[0]
        self.assertFalse(any(argument.startswith("--proxy-server=") for argument in command))

    def test_valid_http_proxy_configuration(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("HTTP proxy")

        profiles.set_proxy(profile_id, True, "http", "proxy.example", "8080")

        self.assertEqual(self.manager.proxy_launch_arguments(
            profiles.get_profile_metadata()[0]
        ), ["--proxy-server=http://proxy.example:8080"])

    def test_valid_https_proxy_configuration(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("HTTPS proxy")

        profiles.set_proxy(profile_id, True, "https", "secure-proxy.example", 8443)

        self.assertEqual(self.manager.proxy_launch_arguments(
            profiles.get_profile_metadata()[0]
        ), ["--proxy-server=https://secure-proxy.example:8443"])

    def test_valid_socks4_proxy_configuration(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("SOCKS4 proxy")

        profiles.set_proxy(profile_id, True, "socks4", "127.0.0.1", 1080)

        self.assertEqual(self.manager.proxy_launch_arguments(
            profiles.get_profile_metadata()[0]
        ), ["--proxy-server=socks4://127.0.0.1:1080"])

    def test_valid_socks5_proxy_configuration_and_ipv6_formatting(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("SOCKS5 proxy")

        profiles.set_proxy(profile_id, True, " SOCKS5 ", "[2001:db8::1]", "1081")

        record = profiles.get_profile_metadata()[0]
        self.assertEqual(record["proxy_host"], "2001:db8::1")
        self.assertEqual(self.manager.proxy_launch_arguments(record), [
            "--proxy-server=socks5://[2001:db8::1]:1081"
        ])

    def test_proxy_input_is_normalized_without_network_access(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Normalized proxy")

        result = profiles.set_proxy(
            profile_id, True, " HTTPS ", " Proxy.Example. ", " 443 "
        )

        self.assertEqual(result["scheme"], "https")
        self.assertEqual(result["host"], "proxy.example")
        self.assertEqual(result["port"], 443)

    def test_parse_host_port(self):
        self.assertEqual(self.manager.parse_proxy_string("proxy.example:8080"), {
            "scheme": "http", "host": "proxy.example", "port": 8080,
        })

    def test_parse_host_port_authentication_is_rejected(self):
        auth = f"{'u' * 5}:{'p' * 7}"
        with self.assertRaises(self.manager.ProxyValidationError):
            self.manager.parse_proxy_string(f"proxy.example:8080:{auth}")

    def test_parse_scheme_host_port(self):
        self.assertEqual(self.manager.parse_proxy_string("socks5://proxy.example:1080"), {
            "scheme": "socks5", "host": "proxy.example", "port": 1080,
        })

    def test_parse_scheme_authentication_is_rejected(self):
        auth = f"{'u' * 5}:{'p' * 7}"
        with self.assertRaises(self.manager.ProxyValidationError):
            self.manager.parse_proxy_string(f"https://{auth}@proxy.example:443")

    def test_bracketed_ipv6_endpoint_is_supported_and_auth_is_rejected(self):
        parsed = self.manager.parse_proxy_string("[2001:db8::1]:1080")
        self.assertEqual(parsed["port"], 1080)
        self.assertIn("2001:db8::1", parsed["host"])

        auth = f"{'u' * 5}:{'p' * 7}"
        with self.assertRaises(self.manager.ProxyValidationError):
            self.manager.parse_proxy_string(f"[2001:db8::1]:1080:{auth}")

    def test_parse_invalid_port_and_malformed_string(self):
        for value in (
            "proxy.example:0",
            "proxy.example:65536",
            "proxy.example:not-a-port",
            "proxy.example",
            "https://user@proxy.example:443",
        ):
            with self.subTest(value=value):
                with self.assertRaises(self.manager.ProxyValidationError):
                    self.manager.parse_proxy_string(value)

    def test_parse_trims_input_and_normalizes_scheme_host_port(self):
        parsed = self.manager.parse_proxy_string("  HTTPS://Proxy.Example.:443  ")

        self.assertEqual(parsed["scheme"], "https")
        self.assertEqual(parsed["host"], "proxy.example")
        self.assertEqual(parsed["port"], 443)

    def test_parse_rejects_unsupported_scheme(self):
        with self.assertRaisesRegex(self.manager.ProxyValidationError, "Unsupported proxy scheme"):
            self.manager.parse_proxy_string("ftp://proxy.example:21")

    def test_invalid_host_is_rejected_before_save(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Invalid host")
        original = self.manager.PROFILES_JSON.read_bytes()

        for host in ("", "proxy host", "http://proxy.example", "user@proxy.example", "proxy.example:80"):
            with self.subTest(host=host):
                with self.assertRaises(self.manager.ProxyValidationError):
                    profiles.set_proxy(profile_id, True, "http", host, 8080)
                self.assertEqual(self.manager.PROFILES_JSON.read_bytes(), original)

    def test_invalid_port_is_rejected_before_save(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Invalid port")
        original = self.manager.PROFILES_JSON.read_bytes()

        for port in ("", "abc", 0, 65536, -1, True):
            with self.subTest(port=port):
                with self.assertRaises(self.manager.ProxyValidationError):
                    profiles.set_proxy(profile_id, True, "http", "proxy.example", port)
                self.assertEqual(self.manager.PROFILES_JSON.read_bytes(), original)

    def test_unsupported_scheme_is_rejected_before_save(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Invalid scheme")
        original = self.manager.PROFILES_JSON.read_bytes()

        with self.assertRaisesRegex(self.manager.ProxyValidationError, "Unsupported proxy scheme"):
            profiles.set_proxy(profile_id, True, "ftp", "proxy.example", 8080)
        self.assertEqual(self.manager.PROFILES_JSON.read_bytes(), original)

    def test_malformed_enabled_proxy_metadata_falls_back_to_off(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Malformed proxy metadata")
        catalog = json.loads(self.manager.PROFILES_JSON.read_text(encoding="utf-8"))
        catalog["profiles"][0].update({
            "proxy_enabled": True,
            "proxy_scheme": "unknown",
            "proxy_host": {"unexpected": "value"},
            "proxy_port": [8080],
        })
        self.manager.PROFILES_JSON.write_text(json.dumps(catalog), encoding="utf-8")

        restarted = self.manager.ProfileManager()
        record = restarted.get_profile_metadata()[0]
        self.assertFalse(restarted.get_proxy(profile_id)["enabled"])
        self.assertEqual(self.manager.proxy_launch_arguments(record), [])

    def test_proxy_persists_after_restart(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Persistent proxy")
        profiles.set_proxy(profile_id, True, "https", "proxy.example", 443)

        restarted = self.manager.ProfileManager()
        self.assertEqual(restarted.get_proxy(profile_id), {
            "enabled": True,
            "scheme": "https",
            "host": "proxy.example",
            "port": 443,
        })

    def test_multiple_profiles_keep_different_proxy_states(self):
        profiles = self.make_profiles()
        first = profiles.create_profile("First proxy")
        second = profiles.create_profile("Second proxy")
        third = profiles.create_profile("No proxy")
        profiles.set_proxy(first, True, "http", "first.example", 8000)
        profiles.set_proxy(second, True, "socks5", "second.example", 9000)

        records = {record["profile_id"]: record for record in profiles.get_profile_metadata()}
        self.assertEqual(self.manager.proxy_launch_arguments(records[first]), [
            "--proxy-server=http://first.example:8000"
        ])
        self.assertEqual(self.manager.proxy_launch_arguments(records[second]), [
            "--proxy-server=socks5://second.example:9000"
        ])
        self.assertEqual(self.manager.proxy_launch_arguments(records[third]), [])

    def test_environment_and_proxy_arguments_coexist_per_profile(self):
        self.make_runtime()
        profiles = self.make_profiles()
        mobile = profiles.create_profile("Mobile with proxy")
        desktop = profiles.create_profile("Desktop without proxy")
        profiles.set_environment(mobile, "mobile")
        profiles.set_proxy(mobile, True, "http", "mobile-proxy.example", 8080)
        profiles.set_environment(desktop, "desktop")

        launcher = self.manager.ChromiumLauncher()
        self.assertTrue(launcher.launch_discord(mobile))
        mobile_command = self.popen.call_args_list[-1].args[0]
        self.assertIn("--use-mobile-user-agent", mobile_command)
        self.assertIn("--proxy-server=http://mobile-proxy.example:8080", mobile_command)

        self.assertTrue(launcher.launch_discord(desktop))
        desktop_command = self.popen.call_args_list[-1].args[0]
        self.assertNotIn("--proxy-server=http://mobile-proxy.example:8080", desktop_command)
        self.assertFalse(any(argument.startswith("--proxy-server=") for argument in desktop_command))

    def test_disabling_proxy_restores_normal_launch_behavior(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Disable proxy")
        profiles.set_proxy(profile_id, True, "http", "proxy.example", 8080)
        profiles.set_proxy(profile_id, False)

        record = profiles.get_profile_metadata()[0]
        self.assertFalse(record["proxy_enabled"])
        self.assertNotIn("proxy_scheme", record)
        self.assertEqual(self.manager.proxy_launch_arguments(record), [])
        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id))
        command = self.popen.call_args.args[0]
        self.assertFalse(any(argument.startswith("--proxy-server=") for argument in command))

    def test_stale_proxy_fields_while_disabled_never_become_active(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Stale disabled proxy")
        catalog = json.loads(self.manager.PROFILES_JSON.read_text(encoding="utf-8"))
        catalog["profiles"][0].update({
            "proxy_enabled": False,
            "proxy_scheme": "http",
            "proxy_host": "stale.example",
            "proxy_port": 8080,
        })
        self.manager.PROFILES_JSON.write_text(json.dumps(catalog), encoding="utf-8")

        record = self.manager.ProfileManager().get_profile_metadata()[0]
        self.assertEqual(self.manager.proxy_launch_arguments(record), [])

    def test_search_and_status_polling_do_not_probe_proxy(self):
        profile_path = self.work / "profiles" / "profile_0001"
        profile_path.mkdir(parents=True)
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.root = Mock()
        app.status_var = FakeVar()
        app.search_var = FakeVar()
        app.sort_method = FakeVar("name")
        app.sort_reverse = False
        app._id_column_index = self.manager.PROFILE_TABLE_DATA_COLUMNS.index("id")
        app._search_after_id = None
        app._status_after_id = None
        app._profile_rows = [{
            "profile_id": "profile_0001", "display_name": "Proxy", "account": "-",
            "environment": "Desktop", "proxy": "On", "status": "Closed",
            "last_opened": "Never", "created_at": "", "last_opened_sort": "",
            "profile_path": str(profile_path),
        }]
        app.table_rows = list(app._profile_rows)
        app.profiles = [("profile_0001", "Proxy")]
        app.selected_profile_ids = set()
        app._closing = False
        app.tree = FakeTree()
        app.tree.insert("", "end", iid="profile_0001", values=(
            "Proxy", "-", "Desktop", "On", "Closed", "Never", "profile_0001"
        ))

        with patch.object(self.manager, "effective_proxy", side_effect=AssertionError("proxy probe")), \
                patch.object(self.manager, "browser_using_directory", return_value=False):
            app.search_var.set("proxy")
            app._schedule_search_filter()
            app._run_search_filter()
            app._poll_status()

        self.assertEqual(app.tree.item("profile_0001", "values")[3], "On")

    def test_proxy_endpoint_is_stored_without_removed_fields(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Proxy endpoint")
        profiles.set_proxy(profile_id, True, "http", "proxy.example", 8080)

        raw = self.manager.PROFILES_JSON.read_text(encoding="utf-8").casefold()
        self.assertNotIn("proxy_username", raw)
        self.assertNotIn("proxy_password", raw)
        record = profiles.get_profile_metadata()[0]
        self.assertEqual(self.manager.proxy_launch_arguments(record), [
            "--proxy-server=http://proxy.example:8080",
        ])
        with self.assertRaises(self.manager.ProxyValidationError):
            profiles.set_proxy(profile_id, True, "http", "userinfo@proxy.example", 8080)

    def test_proxy_gui_has_endpoint_fields_only(self):
        proxy_source = inspect.getsource(self.manager.ProfileManagerApp.edit_proxy).casefold()
        self.assertIn("host", proxy_source)
        self.assertIn("port", proxy_source)
        self.assertNotIn("username_var", proxy_source)
        self.assertNotIn("password_var", proxy_source)

    def test_authenticated_proxy_syntax_is_rejected_without_echoing_input(self):
        auth = f"{'u' * 5}:{'p' * 7}"
        value = f"http://{auth}@proxy.example:8080"
        with self.assertRaises(self.manager.ProxyValidationError) as error:
            self.manager.parse_proxy_string(value)
        self.assertNotIn(value, str(error.exception))

    def test_mobile_default_dpr_is_practical_and_mobile_flags_remain_enabled(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Mobile practical")
        profiles.set_environment(profile_id, "mobile")

        environment = profiles.get_environment(profile_id)
        arguments = self.manager.environment_launch_arguments(
            profiles.get_profile_metadata()[0]
        )
        self.assertEqual(environment["device_scale_factor"], 1.0)
        self.assertIn("--force-device-scale-factor=1", arguments)
        self.assertIn("--use-mobile-user-agent", arguments)
        self.assertIn("--touch-events=enabled", arguments)

    def test_desktop_remains_without_environment_overrides(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Desktop unchanged")
        profiles.set_environment(profile_id, "desktop")

        self.assertEqual(self.manager.environment_launch_arguments(
            profiles.get_profile_metadata()[0]
        ), [])

    def test_custom_dpr_remains_user_configurable(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Custom DPR")
        profiles.set_environment(profile_id, "custom", {
            "width": 1000,
            "height": 700,
            "scale_factor": "1.25",
        })

        environment = profiles.get_environment(profile_id)
        arguments = self.manager.environment_launch_arguments(
            profiles.get_profile_metadata()[0]
        )
        self.assertEqual(environment["device_scale_factor"], 1.25)
        self.assertIn("--force-device-scale-factor=1.25", arguments)

    def test_explicit_mobile_dpr_two_remains_compatible_after_restart(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Explicit mobile DPR")
        profiles.set_environment(profile_id, "mobile", {"device_scale_factor": 2.0})

        restarted = self.manager.ProfileManager()
        environment = restarted.get_environment(profile_id)
        arguments = self.manager.environment_launch_arguments(
            restarted.get_profile_metadata()[0]
        )
        self.assertEqual(environment["device_scale_factor"], 2.0)
        self.assertIn("--force-device-scale-factor=2", arguments)


if __name__ == "__main__":
    unittest.main()
