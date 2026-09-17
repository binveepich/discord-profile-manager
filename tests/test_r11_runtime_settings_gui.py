"""R11 unified Profile Runtime Settings controller and Tk-dialog contracts."""

import ast
import inspect
import textwrap
import unittest
from unittest.mock import Mock, patch

from compatibility.fixtures import DisposableWorkspace
from revamped.gui import TkRevampedApp
from revamped.main import compose
from revamped.processes import ChromiumProcessInspector


class _Variable:
    """Small Tk variable stand-in that keeps this test headless."""

    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    """Record widget construction while accepting the Tk methods used here."""

    def __init__(self, kind, args, kwargs):
        self.kind = kind
        self.args = args
        self.kwargs = kwargs
        self.config_calls = []
        self.bindings = []
        self.destroyed = False

    def grid(self, *args, **kwargs):
        return self

    def pack(self, *args, **kwargs):
        return self

    def columnconfigure(self, *args, **kwargs):
        return None

    def config(self, *args, **kwargs):
        self.config_calls.append((args, kwargs))

    def bind(self, *args, **kwargs):
        self.bindings.append((args, kwargs))

    def title(self, *args, **kwargs):
        self.kwargs["title"] = args[0] if args else kwargs.get("title")

    def transient(self, *args, **kwargs):
        return None

    def grab_set(self):
        return None

    def destroy(self):
        self.destroyed = True


class _TkRecorder:
    """Minimal fake Tk module for checking the Runtime Settings dialog."""

    BOTH = "both"
    LEFT = "left"
    NORMAL = "normal"
    DISABLED = "disabled"

    def __init__(self):
        self.widgets = []
        self.variables = []

    def _widget(self, kind, *args, **kwargs):
        widget = _Widget(kind, args, kwargs)
        self.widgets.append(widget)
        return widget

    def Toplevel(self, *args, **kwargs):
        return self._widget("Toplevel", *args, **kwargs)

    def Frame(self, *args, **kwargs):
        return self._widget("Frame", *args, **kwargs)

    def Label(self, *args, **kwargs):
        return self._widget("Label", *args, **kwargs)

    def Entry(self, *args, **kwargs):
        return self._widget("Entry", *args, **kwargs)

    def Checkbutton(self, *args, **kwargs):
        return self._widget("Checkbutton", *args, **kwargs)

    def Button(self, *args, **kwargs):
        return self._widget("Button", *args, **kwargs)

    def StringVar(self, value=None):
        variable = _Variable(value)
        self.variables.append(variable)
        return variable

    def BooleanVar(self, value=None):
        variable = _Variable(value)
        self.variables.append(variable)
        return variable


class _TtkRecorder:
    def __init__(self, tk):
        self.tk = tk

    def Combobox(self, *args, **kwargs):
        return self.tk._widget("Combobox", *args, **kwargs)


class R11RuntimeSettingsGuiTests(unittest.TestCase):
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chromium/123.0.0.0 Safari/537.36"
    )

    def setUp(self):
        self.workspace = DisposableWorkspace("r11-runtime-settings-gui-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.composition = self._compose()
        self.controller = self.composition.controller
        self.profile_id = self.controller.create_profile("R11 GUI disposable profile")
        self.assertIsNotNone(self.profile_id)

    def _compose(self):
        return compose(
            self.workspace.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )

    def _custom_environment(self):
        return {
            "user_agent": self.USER_AGENT,
            "language": "vi-VN",
            "device_scale_factor": "1.25",
            "touch_mode": True,
            "timezone": "Asia/Ho_Chi_Minh",
            "window_size_policy": "custom",
            "window_width": "1366",
            "window_height": "900",
        }

    @staticmethod
    def _proxy():
        return {
            "enabled": True,
            "scheme": "socks5",
            "host": "127.0.0.1",
            "port": "1080",
        }

    def test_controller_saves_one_runtime_payload_and_restores_it_after_restart(self):
        saved = self.controller.save_runtime_settings(
            "Custom", self._custom_environment(), self._proxy()
        )

        self.assertEqual(saved["environment"]["preset"], "custom")
        self.assertEqual(saved["environment"]["user_agent"], self.USER_AGENT)
        self.assertEqual(saved["environment"]["language"], "vi-VN")
        self.assertEqual(saved["environment"]["device_scale_factor"], 1.25)
        self.assertTrue(saved["environment"]["touch_mode"])
        self.assertEqual(saved["environment"]["window_width"], 1366)
        self.assertEqual(saved["environment"]["window_height"], 900)
        self.assertEqual(saved["environment"]["timezone"], "Asia/Ho_Chi_Minh")
        self.assertFalse(saved["environment"]["timezone_runtime_applied"])
        self.assertEqual(saved["network"], {
            "enabled": True,
            "scheme": "socks5",
            "host": "127.0.0.1",
            "port": 1080,
        })
        self.assertIn("Runtime settings saved", self.controller.status_message)
        self.assertTrue(self.controller.update_action_buttons()["runtime_settings"])

        restarted = self._compose()
        restarted.controller.refresh()
        restarted.controller.set_selection([self.profile_id])
        restored = restarted.controller.runtime_settings_editor_state()

        self.assertEqual(restored, saved)
        self.assertEqual(restored["proxy"], restored["network"])

    def test_visible_sidebar_has_one_runtime_settings_action(self):
        source = textwrap.dedent(inspect.getsource(TkRevampedApp._build_widgets))
        tree = ast.parse(source)
        sidebar_buttons = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_button"
                and len(node.args) >= 4
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[2], ast.Constant)
            ):
                continue
            sidebar_buttons.append((node.args[1].value, node.args[2].value))

        runtime_buttons = [
            button for button in sidebar_buttons
            if "runtime settings" in button[1].casefold()
        ]
        self.assertEqual(runtime_buttons, [("runtime_settings", "Runtime Settings…")])
        self.assertFalse(any(
            label.casefold() in {"environment", "proxy"}
            for _key, label in sidebar_buttons
        ))

    def test_headless_tk_dialog_combines_identity_network_and_unified_save(self):
        self.controller.save_runtime_settings(
            "Custom", self._custom_environment(), self._proxy()
        )
        tk = _TkRecorder()
        app = TkRevampedApp.__new__(TkRevampedApp)
        app.root = Mock()
        app.controller = self.controller
        app.dialogs = Mock()
        app._render = Mock()
        app.tk = tk
        app.ttk = _TtkRecorder(tk)

        app.edit_runtime_settings()

        dialog = next(widget for widget in tk.widgets if widget.kind == "Toplevel")
        labels = [
            widget.kwargs["text"]
            for widget in tk.widgets
            if widget.kind == "Label" and "text" in widget.kwargs
        ]
        buttons = {
            widget.kwargs["text"]: widget
            for widget in tk.widgets
            if widget.kind == "Button" and "text" in widget.kwargs
        }
        timezone_labels = [label for label in labels if "timezone" in label.casefold()]

        self.assertIn("Profile Runtime Settings", dialog.kwargs["title"])
        self.assertIn("Environment identity", labels)
        self.assertIn("Network", labels)
        self.assertIn("User-Agent", labels)
        self.assertTrue(timezone_labels)
        self.assertTrue(any(
            "metadata only" in label.casefold()
            and "not runtime-applied" in label.casefold()
            for label in timezone_labels
        ))
        self.assertIn("Regenerate Environment", buttons)
        self.assertIn("Parse Proxy", buttons)
        self.assertIn("Save", buttons)

        with patch.object(
            self.controller,
            "save_runtime_settings",
            wraps=self.controller.save_runtime_settings,
        ) as save_runtime_settings:
            buttons["Save"].kwargs["command"]()

        save_runtime_settings.assert_called_once()
        preset, environment_config, proxy_config = save_runtime_settings.call_args.args
        self.assertEqual(preset, "Custom")
        self.assertEqual(environment_config["user_agent"], self.USER_AGENT)
        self.assertEqual(environment_config["timezone"], "Asia/Ho_Chi_Minh")
        self.assertEqual(proxy_config, {
            **self._proxy(),
            # The visible scheme selector uses the conventional UI spelling;
            # proxy normalization happens below the controller.
            "scheme": "SOCKS5",
        })
        self.assertTrue(dialog.destroyed)
        app._render.assert_called_once_with()
        app.dialogs.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
