"""R10 environment persistence, real launch assembly, and truthful editor tests."""

import unittest
from unittest.mock import Mock

from compatibility.fixtures import DisposableWorkspace
from revamped import environment
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


class R10EnvironmentTests(unittest.TestCase):
    def compose(self, root):
        return compose(
            root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )

    def test_persisted_presets_reach_actual_launch_assembly_after_restart(self):
        with DisposableWorkspace("r10-environment-") as workspace:
            first = self.compose(workspace.root)
            first.profile_service.initialize_metadata()
            desktop = first.profile_service.create_profile("Disposable Desktop")
            mobile = first.profile_service.create_profile("Disposable Mobile")
            custom = first.profile_service.create_profile("Disposable Custom")
            for profile_id, preset, config in (
                (desktop, "desktop", {}),
                (mobile, "mobile", {}),
                (custom, "custom", {
                    "viewport_width": 1100, "viewport_height": 760,
                    "device_scale_factor": 1.5, "language": "vi-VN",
                    "timezone": "UTC", "mobile_mode": False, "touch_mode": False,
                }),
            ):
                first.controller.refresh()
                first.controller.set_selection([profile_id])
                first.controller.save_environment(preset, config)
                self.assertIn("close and reopen Chromium", first.controller.status_message)

            restarted = self.compose(workspace.root)
            commands = {}
            for profile_id in (desktop, mobile, custom):
                record = restarted.profile_service.get_profile_record(profile_id)
                directory = restarted.profile_service.require_profile_dir(profile_id)
                commands[profile_id] = restarted.launcher.build_command(
                    profile_id, directory, record,
                )
                self.assertIn(f"--user-data-dir={directory}", commands[profile_id])
                self.assertTrue(directory.is_relative_to(workspace.root))

            self.assertFalse(any(arg.startswith("--window-size=") for arg in commands[desktop]))
            self.assertIn("--window-size=390,844", commands[mobile])
            self.assertIn("--force-device-scale-factor=1", commands[mobile])
            self.assertIn("--lang=en-US", commands[mobile])
            self.assertIn("--touch-events=enabled", commands[mobile])
            self.assertIn("--window-size=1100,760", commands[custom])
            self.assertIn("--force-device-scale-factor=1.5", commands[custom])
            self.assertIn("--lang=vi-VN", commands[custom])
            self.assertIn("--touch-events=disabled", commands[custom])
            self.assertFalse(any("timezone" in arg for arg in commands[custom]))

    def test_runtime_notes_explain_unsupported_and_partial_settings(self):
        mobile_notes = " ".join(environment.environment_runtime_notes({
            "environment_preset": "mobile",
        }))
        self.assertIn("unsupported on Windows", mobile_notes)
        self.assertIn("Chromium ignores", mobile_notes)
        self.assertIn("not an exact page viewport", mobile_notes)
        custom_notes = " ".join(environment.environment_runtime_notes({
            "environment_preset": "custom",
            "environment_config": {"timezone": "UTC", "viewport_width": 1000},
        }))
        self.assertIn("Timezone is saved only", custom_notes)
        self.assertIn("Both window width and height are required", custom_notes)

    def test_mobile_editor_displays_persisted_supported_overrides(self):
        with DisposableWorkspace("r10-mobile-editor-") as workspace:
            composition = self.compose(workspace.root)
            profile_id = composition.profile_service.create_profile("Disposable Mobile")
            composition.profile_service.set_environment(profile_id, "mobile", {
                "viewport_width": 720, "viewport_height": 1000,
                "language": "vi-VN", "timezone": "UTC",
            })
            composition.controller.refresh()
            composition.controller.set_selection([profile_id])
            state = composition.controller.environment_editor_state()
            self.assertEqual(state["viewport_width"], 720)
            self.assertEqual(state["viewport_height"], 1000)
            self.assertEqual(state["language"], "vi-VN")
            self.assertEqual(state["timezone"], "UTC")
            self.assertFalse(state["editable"])

    def test_tk_editor_switches_defaults_editability_and_preserves_custom_values(self):
        app = TkRevampedApp.__new__(TkRevampedApp)
        app.root = Mock()
        app.dialogs = Mock()
        app.controller = Mock()
        app.controller.get_selected_profile.return_value = ("profile_0001", "Disposable")
        app.controller.environment_editor_state.return_value = environment.environment_editor_state("desktop")
        app._render = Mock()
        app.tk = Mock(NORMAL="normal", DISABLED="disabled", LEFT="left", BOTH="both")
        app.ttk = Mock()
        variables = []
        entries = []

        def variable_factory(value=None):
            result = _Variable(value)
            variables.append(result)
            return result

        def entry_factory(*args, **kwargs):
            result = Mock()
            entries.append(result)
            return result

        app.tk.StringVar.side_effect = variable_factory
        app.tk.BooleanVar.side_effect = variable_factory
        app.tk.Entry.side_effect = entry_factory
        app.edit_environment()

        preset = variables[0]
        width, height, language, timezone, mobile, touch = variables[1:]
        change_preset = app.ttk.Combobox.return_value.bind.call_args.args[1]
        for entry in entries:
            entry.config.assert_called_with(state="disabled")
        preset.set("Mobile")
        change_preset()
        self.assertEqual(width.get(), 390)
        self.assertEqual(height.get(), 844)
        self.assertTrue(mobile.get())
        preset.set("Custom")
        change_preset()
        self.assertEqual(width.get(), "")
        for entry in entries[:3]:
            entry.config.assert_called_with(state="normal")
        self.assertFalse(mobile.get())
        width.set("1100")
        height.set("760")
        language.set("vi-VN")
        touch.set(True)
        preset.set("Desktop")
        change_preset()
        self.assertEqual(width.get(), "Chromium default")
        preset.set("Custom")
        change_preset()
        self.assertEqual(width.get(), 1100)
        self.assertEqual(height.get(), 760)
        self.assertEqual(language.get(), "vi-VN")
        self.assertTrue(touch.get())

        save_call = next(
            call for call in app.tk.Button.call_args_list
            if call.kwargs.get("text") == "Save"
        )
        save_call.kwargs["command"]()
        saved_preset, saved_config = app.controller.save_environment.call_args.args
        self.assertEqual(saved_preset, "custom")
        self.assertEqual(saved_config["viewport_width"], 1100)
        self.assertEqual(saved_config["viewport_height"], 760)
        self.assertFalse(saved_config["mobile_mode"])
        self.assertTrue(saved_config["touch_mode"])
        self.assertTrue(any(
            "unsupported on Windows" in call.kwargs.get("text", "")
            for call in app.tk.Label.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
