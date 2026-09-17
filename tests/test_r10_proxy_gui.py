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

    def parse_authenticated_input(self):
        self.pasted.set("http://synthetic-user:synthetic-secret@proxy.example:8080")
        self.parse()
        self.assertEqual(self.pasted.get(), "")
        self.assertIn("Save will reject", self.note.get())
        for variable in self.variables:
            self.assertNotIn("synthetic-user", str(variable.get()))
            self.assertNotIn("synthetic-secret", str(variable.get()))

    def assert_no_saved_credentials(self):
        catalog = self.composition.paths.profiles_json.read_text(encoding="utf-8")
        self.assertNotIn("synthetic-user", catalog)
        self.assertNotIn("synthetic-secret", catalog)

    def test_authenticated_parse_then_enabled_save_leaves_profile_unchanged(self):
        before = self.composition.profile_service.get_profile_record(self.profile_id)
        self.parse_authenticated_input()

        self.save()

        self.save_spy.assert_not_called()
        self.app.dialogs.error.assert_called_once()
        self.assertIn("Authenticated proxy launch", self.app.dialogs.error.call_args.args[1])
        self.assertNotIn("synthetic-secret", self.app.dialogs.error.call_args.args[1])
        self.app.tk.Toplevel.return_value.destroy.assert_not_called()
        self.assertEqual(self.composition.profile_service.get_profile_record(self.profile_id), before)
        self.assert_no_saved_credentials()

    def test_unauthenticated_reparse_clears_rejection_and_saves_endpoint(self):
        self.parse_authenticated_input()
        self.save()
        self.save_spy.assert_not_called()
        self.pasted.set("socks5://127.0.0.1:1080")
        self.parse()

        self.save()

        self.save_spy.assert_called_once_with(True, "SOCKS5", "127.0.0.1", "1080")
        self.assertEqual(self.composition.profile_service.get_proxy(self.profile_id), {
            "enabled": True, "scheme": "socks5", "host": "127.0.0.1", "port": 1080,
        })
        self.app.tk.Toplevel.return_value.destroy.assert_called_once()
        self.assertNotIn("Save will reject", self.note.get())
        self.assert_no_saved_credentials()

    def test_explicit_proxy_off_is_allowed_after_authenticated_parse(self):
        self.composition.profile_service.set_proxy(self.profile_id, True, "http", "127.0.0.1", 8081)
        self.parse_authenticated_input()
        self.mode.set("Off")

        self.save()

        self.save_spy.assert_called_once_with(False, "HTTP", "proxy.example", "8080")
        self.assertFalse(self.composition.profile_service.get_proxy(self.profile_id)["enabled"])
        record = self.composition.profile_service.get_profile_record(self.profile_id)
        for field in ("proxy_scheme", "proxy_host", "proxy_port", "username", "password"):
            self.assertNotIn(field, record)
        self.app.dialogs.error.assert_not_called()
        self.app.tk.Toplevel.return_value.destroy.assert_called_once()
        self.assert_no_saved_credentials()


if __name__ == "__main__":
    unittest.main()
