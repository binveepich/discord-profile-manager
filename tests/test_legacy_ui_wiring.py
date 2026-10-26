"""Legacy Tk wiring regressions with Tk stubbed out, so no window is opened.

The legacy editors are built against a recording fake of tkinter. These tests
prove that the environment and proxy dialogs construct, that the proxy dialog
exposes endpoint fields only, and that the Save and paste-parse callbacks run
without AttributeError or NameError.
"""

import unittest
from unittest.mock import MagicMock, patch

import test_m1_runtime as m1
import test_m6_gui as m6
from test_m6_gui import FakeVar


class StubVar(FakeVar):
    """A Tk variable that stores its value and accepts trace registrations."""

    def trace_add(self, _mode, _callback):
        return None


class WidgetRecorder:
    """Stands in for tkinter constructors and remembers each widget's options."""

    def __init__(self):
        self.widgets = []

    def constructor(self, kind):
        def build(*_args, **kwargs):
            widget = MagicMock(name=kind)
            widget.kind = kind
            widget.options = kwargs
            self.widgets.append(widget)
            return widget

        return build

    def since(self, start, kind):
        return [widget for widget in self.widgets[start:] if widget.kind == kind]

    def button(self, start, text):
        return next(
            widget for widget in self.since(start, "Button")
            if widget.options.get("text") == text
        )


def make_fake_tk(recorder):
    fake = MagicMock(name="tkinter")
    fake.StringVar = StubVar
    fake.BooleanVar = StubVar
    for kind in ("Toplevel", "Frame", "LabelFrame", "Label", "Entry", "Button", "Checkbutton"):
        getattr(fake, kind).side_effect = recorder.constructor(kind)
    return fake


def make_fake_ttk(recorder):
    fake = MagicMock(name="ttk")
    fake.Combobox.side_effect = recorder.constructor("Combobox")
    return fake


class LegacyWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    setUp = m6.M6GUITests.setUp

    def open_app(self):
        recorder = WidgetRecorder()
        messagebox = MagicMock(name="messagebox")
        self.stack.enter_context(patch.object(self.manager, "tk", make_fake_tk(recorder)))
        self.stack.enter_context(patch.object(self.manager, "ttk", make_fake_ttk(recorder)))
        self.stack.enter_context(patch.object(self.manager, "messagebox", messagebox))
        self.stack.enter_context(patch.object(self.manager, "browser_using_directory", return_value=False))
        app = self.manager.ProfileManagerApp(MagicMock(name="root"))
        return app, recorder, messagebox

    def test_environment_dialog_builds_and_saves_selected_preset(self):
        app, recorder, _messagebox = self.open_app()
        profile_id = app.profile_manager.create_profile("Environment wiring")
        app.refresh_list()

        start = len(recorder.widgets)
        with patch.object(app, "get_selected_profile", return_value=(profile_id, "Environment wiring")):
            app.edit_environment()

        (preset_box,) = [
            box for box in recorder.since(start, "Combobox")
            if box.options.get("values") == ("Desktop", "Mobile", "Custom")
        ]
        preset_box.options["textvariable"].set("Mobile")
        recorder.button(start, "Save").options["command"]()

        record = next(
            item for item in app.profile_manager.get_profile_metadata()
            if item["profile_id"] == profile_id
        )
        self.assertEqual(self.manager.effective_environment(record)[0], "mobile")

    def test_proxy_dialog_exposes_endpoint_fields_only(self):
        app, recorder, _messagebox = self.open_app()
        profile_id = app.profile_manager.create_profile("Proxy fields")
        app.refresh_list()

        start = len(recorder.widgets)
        with patch.object(app, "get_selected_profile", return_value=(profile_id, "Proxy fields")):
            app.edit_proxy()

        labels = [label.options.get("text") for label in recorder.since(start, "Label")]
        self.assertIn("Host", labels)
        self.assertIn("Port", labels)
        self.assertNotIn("Username", labels)
        self.assertNotIn("Password", labels)
        self.assertFalse([entry for entry in recorder.since(start, "Entry") if entry.options.get("show")])

    def test_proxy_paste_with_credentials_is_refused_and_not_saved(self):
        app, recorder, messagebox = self.open_app()
        profile_id = app.profile_manager.create_profile("Proxy paste")
        app.refresh_list()

        start = len(recorder.widgets)
        with patch.object(app, "get_selected_profile", return_value=(profile_id, "Proxy paste")):
            app.edit_proxy()

        # The paste box is the first Entry the proxy dialog creates.
        paste_entry = recorder.since(start, "Entry")[0]
        paste_entry.options["textvariable"].set("http://user:hunter2@proxy.example:8080")
        parse_button = recorder.button(start, "Parse")
        parse_callback = next(
            call.kwargs["command"] for call in parse_button.configure.call_args_list
            if "command" in call.kwargs
        )
        parse_callback()

        messagebox.showerror.assert_called_once()
        self.assertNotIn("hunter2", str(messagebox.showerror.call_args))
        self.assertFalse(app.profile_manager.get_proxy(profile_id)["enabled"])

    def test_proxy_save_persists_endpoint_only(self):
        app, recorder, _messagebox = self.open_app()
        profile_id = app.profile_manager.create_profile("Proxy save")
        app.refresh_list()

        start = len(recorder.widgets)
        with patch.object(app, "get_selected_profile", return_value=(profile_id, "Proxy save")):
            app.edit_proxy()

        mode_box = next(
            box for box in recorder.since(start, "Combobox")
            if box.options.get("values") == ("Off", "Enabled")
        )
        mode_box.options["textvariable"].set("Enabled")
        # Entries are created in order: paste box, Host, Port.
        _paste, host_entry, port_entry = recorder.since(start, "Entry")[:3]
        host_entry.options["textvariable"].set("proxy.example")
        port_entry.options["textvariable"].set("8080")
        recorder.button(start, "Save").options["command"]()

        self.assertEqual(app.profile_manager.get_proxy(profile_id), {
            "enabled": True, "scheme": "http", "host": "proxy.example", "port": 8080,
        })


if __name__ == "__main__":
    unittest.main()
