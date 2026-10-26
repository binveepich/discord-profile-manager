"""R10 proxy editor rejects authenticated input instead of discarding its auth."""

import unittest
from unittest.mock import Mock, patch

from compatibility.fixtures import DisposableWorkspace
from revamped.gui import TkRevampedApp
from revamped.main import compose
from revamped.processes import ChromiumProcessInspector


class _Variable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class R10ProxyGuiTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("r10-proxy-gui-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.composition = compose(
            self.workspace.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )
        self.profile_id = self.composition.controller.create_profile("Disposable proxy editor")
        self.app = TkRevampedApp.__new__(TkRevampedApp)
        self.app.root = Mock()
        self.app.dialogs = Mock()
        self.app.controller = self.composition.controller
        self.app._render = Mock()
        self.app.tk = Mock(LEFT="left", BOTH="both")
        self.app.ttk = Mock()
        self.variables = []

        def variable_factory(value=None):
            variable = _Variable(value)
            self.variables.append(variable)
            return variable

        self.app.tk.StringVar.side_effect = variable_factory
        self.app.edit_proxy()
        self.mode, self.scheme, self.host, self.port, self.pasted, self.note = self.variables
        callbacks = {
            call.kwargs["text"]: call.kwargs["command"]
            for call in self.app.tk.Button.call_args_list
        }
        self.parse = callbacks["Parse"]
        self.save = callbacks["Save"]
        self.save_spy = self.enterContext(patch.object(
            self.app.controller,
            "save_proxy",
            wraps=self.app.controller.save_proxy,
        ))

    def authenticated_input(self):
        auth = f"{'u' * 5}:{'p' * 7}"
        return f"http://{auth}@proxy.example:8081"

    def assert_no_saved_credentials(self):
        catalog = self.composition.paths.profiles_json.read_text(encoding="utf-8")
        self.assertNotIn("proxy_username", catalog)
        self.assertNotIn("proxy_password", catalog)

    def test_authenticated_proxy_input_is_rejected_without_saving(self):
        before = self.composition.profile_service.get_profile_record(self.profile_id)
        catalog_before = self.composition.paths.profiles_json.read_bytes()
        self.pasted.set(self.authenticated_input())
        self.parse()
        self.app.dialogs.error.assert_called_once()
        self.save_spy.assert_not_called()
        self.assertEqual(self.composition.profile_service.get_profile_record(self.profile_id), before)
        self.assertEqual(self.composition.paths.profiles_json.read_bytes(), catalog_before)
        self.assert_no_saved_credentials()

    def test_endpoint_parse_and_save_round_trip(self):
        self.pasted.set("https://proxy.example:1080")
        self.parse()
        self.save()
        self.save_spy.assert_called_once_with(True, "HTTPS", "proxy.example", "1080")
        self.assertEqual(self.composition.profile_service.get_proxy(self.profile_id), {
            "enabled": True, "scheme": "https", "host": "proxy.example", "port": 1080,
        })
        self.app.tk.Toplevel.return_value.destroy.assert_called_once()
        self.assert_no_saved_credentials()

    def test_proxy_off_is_allowed_after_rejected_authenticated_input(self):
        self.composition.profile_service.set_proxy(self.profile_id, True, "http", "proxy.example", 8081)
        self.pasted.set(self.authenticated_input())
        self.parse()
        self.mode.set("Off")
        self.save()
        self.save_spy.assert_called_once()
        self.assertFalse(self.composition.profile_service.get_proxy(self.profile_id)["enabled"])
        record = self.composition.profile_service.get_profile_record(self.profile_id)
        self.assertNotIn("proxy_username", record)
        self.assertNotIn("proxy_password", record)
        self.app.dialogs.error.assert_called_once()
        self.app.tk.Toplevel.return_value.destroy.assert_called_once()
        self.assert_no_saved_credentials()


if __name__ == "__main__":
    unittest.main()
