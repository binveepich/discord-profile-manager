"""M2 safety and compatibility regressions; all browser/account data is synthetic."""

import json
import stat
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_m1_runtime as m1


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    setUp = m1.RuntimeTests.setUp
    cleanup_workspace = m1.RuntimeTests.cleanup_workspace
    make_runtime = m1.RuntimeTests.make_runtime
    make_profiles = m1.RuntimeTests.make_profiles
    make_launch_profile = m1.RuntimeTests.make_launch_profile
    make_autofill_source = m1.RuntimeTests.make_autofill_source

    def write_registry(self, raw):
        self.data.mkdir(parents=True, exist_ok=True)
        self.manager.LOCAL_STATE.write_bytes(raw)

    def fake_app(self, selected):
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.get_selected_profiles = Mock(return_value=selected)
        app.profile_manager = self.manager.ProfileManager()
        app.launcher = self.manager.ChromiumLauncher()
        app.update_status = Mock()
        app.refresh_list = Mock()
        return app

    def test_malformed_metadata_is_never_reset_or_overwritten(self):
        invalid = [b'{broken', b'[]', b'{}', b'{"profile":[]}', b'{"profile":{"info_cache":[]}}',
                   b'{"profile":{"info_cache":{"Profile 1":null}}}',
                   b'{"profile":{"info_cache":{"Profile 1":{"name":3}}}}',
                   b'{"profile":{"info_cache":{"Profile 1":{"created":"yesterday"}}}}',
                   b'{"profile":{"info_cache":{"Profile 1":{"created":NaN}}}}',
                   b'{"profile":{"info_cache":{"Profile 1":{},"profile 1":{}}}}',
                   b'{"profile":{"info_cache":{"Profile 1":{},"Profile 1":{}}}}',
                   b'\xff\xfeinvalid']
        for raw in invalid:
            with self.subTest(raw=raw[:25]):
                self.write_registry(raw)
                profiles = self.manager.ProfileManager()
                for action in [profiles.get_profiles, lambda: profiles.create_profile('Test'),
                               lambda: profiles.rename_profile('Profile 1', 'Renamed'),
                               lambda: profiles.delete_profile('Profile 1')]:
                    with self.assertRaises(self.manager.ProfileManagerError):
                        action()
                    self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), raw)

    def test_windows_alias_ids_are_rejected_without_touching_data(self):
        invalid = ['..', '.', '', 'Profile 1.', 'Profile 1 ', ' Profile 1', 'CON', 'nul.txt',
                   'COM1', 'LPT9.log', '../Profile 2', 'a/b', 'a\\b', 'C:\\outside',
                   'C:relative', '\\\\server\\share', 'Profile 1:stream', 'bad\x00id']
        for pid in invalid:
            with self.subTest(pid=repr(pid)):
                with self.assertRaises(self.manager.ProfileManagerError):
                    self.manager.ProfileManager().get_profile_dir(pid)
                self.write_registry(json.dumps({'profile': {'info_cache': {pid: {}}}}).encode())
                with self.assertRaises(self.manager.ProfileManagerError):
                    self.manager.LocalStateManager().load()

    def test_bom_metadata_and_legacy_unknown_fields_are_preserved(self):
        raw = b'\xef\xbb\xbf{"profile":{"info_cache":{"Default":{}}},"os_crypt":{"fixture":"untouched"}}'
        self.write_registry(raw)
        profiles = self.manager.ProfileManager()
        self.assertEqual(profiles.get_profiles(), [('Default', 'Default')])
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), raw)

    def test_missing_registry_with_existing_directories_blocks_startup_reset(self):
        profile = self.data / 'Profile 7'
        profile.mkdir(parents=True)
        (profile / 'session.fixture').write_text('preserve')
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().create_profile('New')
        self.make_runtime()
        with patch.object(self.manager.tk, 'Tk') as root, \
                patch.object(self.manager.messagebox, 'showerror') as error, \
                patch.object(self.manager, 'ProfileManagerApp') as app:
            self.manager.main()
        error.assert_called_once()
        app.assert_not_called()
        root.return_value.destroy.assert_called_once()
        self.assertFalse(self.manager.LOCAL_STATE.exists())
        self.assertEqual((profile / 'session.fixture').read_text(), 'preserve')

    def test_missing_registry_with_existing_file_blocks_startup_reset(self):
        self.data.mkdir(parents=True)
        orphan = self.data / 'Profile 7'
        orphan.write_bytes(b'preserve')
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().create_profile('New')
        self.assertFalse(self.manager.LOCAL_STATE.exists())
        self.assertEqual(orphan.read_bytes(), b'preserve')

    def test_unreadable_registry_is_not_replaced(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('synthetic denial')):
            with self.assertRaises(self.manager.ProfileManagerError):
                self.manager.LocalStateManager().load()
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), b'{"profile":{"info_cache":{}}}')

    def test_orphaned_directory_and_file_ids_are_not_reused(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        orphan = self.data / 'profile 9'
        orphan.mkdir()
        marker = orphan / 'session.fixture'
        marker.write_bytes(b'old data')
        (self.data / 'Profile 12').write_bytes(b'not a directory')
        pid = self.manager.ProfileManager().create_profile('New')
        self.assertEqual(pid, 'Profile 13')
        self.assertEqual(marker.read_bytes(), b'old data')

    def test_failed_initialization_does_not_publish_metadata(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        original = self.manager.LOCAL_STATE.read_bytes()
        profiles = self.manager.ProfileManager()
        with patch.object(profiles, '_initialize_profile_structure', side_effect=OSError('synthetic full disk')):
            with self.assertRaises(OSError):
                profiles.create_profile('New')
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), original)

    def test_failed_create_save_keeps_unregistered_directory_and_never_reuses_it(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        profiles = self.manager.ProfileManager()
        with patch.object(profiles.local_state, 'save', side_effect=self.manager.ProfileManagerError('synthetic write failure')):
            with self.assertRaises(self.manager.ProfileManagerError):
                profiles.create_profile('New')
        self.assertTrue((self.data / 'Profile 1' / 'Default' / 'Preferences').is_file())
        self.assertEqual(profiles.get_profiles(), [])
        self.assertEqual(profiles.create_profile('Next'), 'Profile 2')

    def test_unknown_profile_and_missing_directory_never_launch(self):
        self.make_runtime()
        self.write_registry(b'{"profile":{"info_cache":{"Profile 1":{"name":"Missing"}}}}')
        for pid in ['Profile 1', 'Profile 99']:
            with self.assertRaises(self.manager.ProfileManagerError):
                self.manager.ChromiumLauncher().launch_discord(pid)
        self.popen.assert_not_called()
        self.assertFalse((self.data / 'Profile 1').exists())

    def test_missing_data_root_is_reported_without_filesystem_error(self):
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().require_profile_dir('Profile 1')
        self.assertFalse(self.data.exists())

    def test_account_setup_cannot_recreate_missing_profile(self):
        self.make_autofill_source()
        self.write_registry(b'{"profile":{"info_cache":{"Profile 1":{}}}}')
        accounts = self.manager.AccountManager(self.manager.ProfileManager())
        with self.assertRaises(self.manager.ProfileManagerError):
            accounts.set_account('Profile 1', 'fixture@example.invalid:synthetic-password')
        self.assertFalse((self.data / 'Profile 1').exists())

    def test_new_profile_initializes_chromium_default_preferences(self):
        profiles = self.make_profiles()
        pid = profiles.create_profile('New')
        path = profiles.get_profile_dir(pid)
        self.assertTrue((path / 'Default' / 'Preferences').is_file())
        self.assertFalse((path / 'Preferences').exists())

    def test_unopened_legacy_profile_is_supported_without_moving_preferences(self):
        self.make_runtime()
        self.write_registry(b'{"profile":{"info_cache":{"Profile 1":{"name":"Legacy"}}}}')
        profile = self.data / 'Profile 1'
        profile.mkdir()
        prefs = profile / 'Preferences'
        prefs.write_bytes(b'{"profile":{"name":"Profile 1"},"extensions":{"ui":{"developer_mode":true}}}')
        original = prefs.read_bytes()
        self.assertTrue(self.manager.ChromiumLauncher().launch_discord('Profile 1'))
        self.assertEqual(prefs.read_bytes(), original)
        self.assertFalse((profile / 'Default').exists())  # mocked Chromium has not created it

    def test_existing_independent_legacy_browser_state_is_preserved(self):
        self.make_runtime()
        profile = self.make_launch_profile()
        state = profile / 'Local State'
        state.write_bytes(b'{"profile":{"last_used":"Default"},"os_crypt":{"fixture":"preserve"}}')
        marker = profile / 'Default' / 'session.fixture'
        marker.write_bytes(b'synthetic persisted session')
        before = {path: path.read_bytes() for path in (state, marker, profile / 'Default' / 'Preferences')}
        self.assertTrue(self.manager.ChromiumLauncher().launch_discord('Profile 1'))
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_flat_legacy_session_data_is_not_opened_as_an_empty_profile(self):
        self.make_runtime()
        profile = self.make_launch_profile()
        (profile / 'Local Storage').mkdir()
        marker = profile / 'Local Storage' / 'keep.fixture'
        marker.write_text('legacy data')
        with self.assertRaisesRegex(self.manager.ProfileManagerError, 'shared-root subprofile'):
            self.manager.ChromiumLauncher().launch_discord('Profile 1')
        self.popen.assert_not_called()
        self.assertEqual(marker.read_text(), 'legacy data')

    def test_malformed_chromium_local_state_blocks_launch_without_repair(self):
        self.make_runtime()
        profile = self.make_launch_profile()
        state = profile / 'Local State'
        state.write_bytes(b'{broken browser state')
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ChromiumLauncher().launch_discord('Profile 1')
        self.popen.assert_not_called()
        self.assertEqual(state.read_bytes(), b'{broken browser state')

    def test_invalid_or_missing_browser_last_used_directory_is_rejected(self):
        self.make_runtime()
        profile = self.make_launch_profile()
        for pid in ('../Profile 2', 'Profile 404'):
            (profile / 'Local State').write_text(json.dumps({'profile': {'last_used': pid}}))
            with self.assertRaises(self.manager.ProfileManagerError):
                self.manager.ChromiumLauncher().launch_discord('Profile 1')
        self.popen.assert_not_called()

    def test_profile_junction_is_rejected_even_if_it_points_inside_data_root(self):
        profile = self.make_launch_profile()
        original = Path.lstat
        def linked(path, *args, **kwargs):
            if path == profile:
                return Mock(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', linked):
            with self.assertRaises(self.manager.ProfileManagerError):
                self.manager.ProfileManager().get_profile_dir('Profile 1')

    def test_inner_browser_profile_junction_is_rejected(self):
        profile = self.make_launch_profile()
        original = Path.lstat
        def linked(path, *args, **kwargs):
            if path == profile / 'Default':
                return Mock(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', linked):
            with self.assertRaises(self.manager.ProfileManagerError):
                self.manager.ProfileManager().get_browser_profile_dir('Profile 1')

    def test_extension_path_from_another_profile_is_rejected(self):
        self.make_runtime()
        self.make_launch_profile('Profile 1')
        other = self.make_launch_profile('Profile 2') / 'Unpacked Extensions'
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ChromiumLauncher().launch_discord('Profile 1', [other])
        self.popen.assert_not_called()

    def test_running_profile_is_not_deleted(self):
        profile = self.make_launch_profile()
        original = self.manager.LOCAL_STATE.read_bytes()
        process = Mock(info={'name': 'chrome.exe'})
        process.cmdline.return_value = ['chrome.exe', f'--user-data-dir={profile}']
        self.processes.return_value = [process]
        with self.assertRaisesRegex(self.manager.ProfileManagerError, 'Close Chromium'):
            self.manager.ProfileManager().delete_profile('Profile 1')
        self.assertTrue(profile.is_dir())
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), original)

    def test_running_profile_can_be_renamed_without_changing_browser_data(self):
        profile = self.make_launch_profile()
        original = (profile / 'Default' / 'Preferences').read_bytes()
        process = Mock(info={'name': 'chrome.exe'})
        process.cmdline.return_value = ['chrome.exe', f'--user-data-dir={profile}']
        self.processes.return_value = [process]
        self.manager.ProfileManager().rename_profile('Profile 1', 'Running renamed')
        self.assertEqual((profile / 'Default' / 'Preferences').read_bytes(), original)

    def test_running_browser_is_detected_after_manager_restart(self):
        self.make_runtime()
        profile = self.make_launch_profile()
        process = Mock(info={'name': 'chrome.exe'})
        process.cmdline.return_value = ['chrome.exe', '--user-data-dir', str(profile)]
        self.processes.return_value = [process]
        self.assertFalse(self.manager.ChromiumLauncher().launch_discord('Profile 1'))
        self.popen.assert_not_called()

    def test_repeat_open_and_chromium_restart_keep_the_same_root(self):
        self.make_runtime()
        self.make_launch_profile()
        launcher = self.manager.ChromiumLauncher()
        self.assertTrue(launcher.launch_discord('Profile 1'))
        self.assertFalse(launcher.launch_discord('Profile 1'))
        self.popen.return_value.poll.return_value = 0
        self.assertTrue(launcher.launch_discord('Profile 1'))
        self.assertEqual(self.popen.call_count, 2)
        self.assertEqual(self.popen.call_args_list[0].args[0], self.popen.call_args_list[1].args[0])

    def test_immediate_chromium_failure_is_reported(self):
        self.make_runtime()
        self.make_launch_profile()
        self.popen.return_value.poll.return_value = 1
        with self.assertRaisesRegex(self.manager.ProfileManagerError, 'exited'):
            self.manager.ChromiumLauncher().launch_discord('Profile 1')

    def test_sandboxed_renderer_uses_readable_browser_parent(self):
        profile = self.make_launch_profile()
        process = Mock(info={'name': 'chrome.exe'})
        process.cmdline.side_effect = self.manager.psutil.AccessDenied(101)
        parent = process.parent.return_value
        parent.name.return_value = 'chrome.exe'
        parent.cmdline.return_value = ['chrome.exe', f'--user-data-dir={profile}']
        self.processes.return_value = [process]
        self.assertTrue(self.manager.browser_using_directory(profile))

    def test_uninspectable_browser_blocks_destructive_action(self):
        profile = self.make_launch_profile()
        process = Mock(info={'name': 'chrome.exe'})
        process.cmdline.side_effect = self.manager.psutil.AccessDenied(101)
        process.parent.return_value = None
        self.processes.return_value = [process]
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().delete_profile('Profile 1')
        self.assertTrue(profile.is_dir())

    def test_exited_process_does_not_block_profiles(self):
        process = Mock(info={'name': 'chrome.exe'})
        process.cmdline.side_effect = self.manager.psutil.NoSuchProcess(101)
        self.processes.return_value = [process]
        self.assertFalse(self.manager.browser_using_directory(self.data / 'Profile 1'))

    def test_shared_root_browser_blocks_metadata_mutations(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        process = Mock(info={'name': 'chrome.exe'})
        process.cmdline.return_value = ['chrome.exe', f'--user-data-dir={self.data}']
        self.processes.return_value = [process]
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().create_profile('New')

    def test_delete_rename_failure_preserves_registry(self):
        profile = self.make_launch_profile()
        original = self.manager.LOCAL_STATE.read_bytes()
        with patch.object(Path, 'rename', side_effect=PermissionError('synthetic locked file')):
            with self.assertRaises(OSError):
                self.manager.ProfileManager().delete_profile('Profile 1')
        self.assertTrue(profile.is_dir())
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), original)

    def test_delete_metadata_failure_restores_directory(self):
        profile = self.make_launch_profile()
        original = self.manager.LOCAL_STATE.read_bytes()
        profiles = self.manager.ProfileManager()
        with patch.object(profiles.local_state, 'save', side_effect=self.manager.ProfileManagerError('synthetic failure')):
            with self.assertRaises(self.manager.ProfileManagerError):
                profiles.delete_profile('Profile 1')
        self.assertTrue(profile.is_dir())
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), original)
        self.assertEqual(list(self.data.glob('.deleting-*')), [])

    def test_failed_delete_cleanup_reports_preserved_staging_location(self):
        profile = self.make_launch_profile()
        with patch.object(self.manager.shutil, 'rmtree', side_effect=PermissionError('synthetic locked file')):
            with self.assertRaisesRegex(self.manager.ProfileManagerError, '.deleting-'):
                self.manager.ProfileManager().delete_profile('Profile 1')
        self.assertFalse(profile.exists())
        self.assertEqual(len(list(self.data.glob('.deleting-*'))), 1)
        self.assertEqual(self.manager.ProfileManager().get_profiles(), [])

    def test_interrupted_delete_is_reported_after_restart(self):
        profile = self.make_launch_profile()
        pending = self.data / '.deleting-Profile 1-fixture'
        self.assertTrue(pending.resolve().is_relative_to(self.work))
        profile.rename(pending)
        with self.assertRaisesRegex(self.manager.ProfileManagerError, 'interrupted deletion'):
            self.manager.ProfileManager().require_profile_dir('Profile 1')
        self.assertTrue(pending.is_dir())

    def test_confirmed_deletion_can_remove_missing_directory_metadata(self):
        self.write_registry(b'{"profile":{"info_cache":{"Profile 1":{}}}}')
        self.manager.ProfileManager().delete_profile('Profile 1')
        self.assertEqual(self.manager.ProfileManager().get_profiles(), [])

    def test_concurrent_manager_mutations_are_blocked(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        state = self.manager.LocalStateManager()
        with state.operation():
            with self.assertRaisesRegex(self.manager.ProfileManagerError, 'operation is in progress'):
                self.manager.ProfileManager().create_profile('Concurrent')
        self.assertEqual(self.manager.ProfileManager().create_profile('Next'), 'Profile 1')

    def test_stale_registry_write_is_rejected(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        first, second = self.manager.LocalStateManager(), self.manager.LocalStateManager()
        stale = first.load()
        latest = second.load()
        latest['preserved'] = True
        second.save(latest)
        with self.assertRaises(self.manager.ProfileManagerError):
            first.save(stale)
        self.assertTrue(second.load()['preserved'])

    def test_failed_atomic_replace_preserves_original_metadata(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        original = self.manager.LOCAL_STATE.read_bytes()
        state = self.manager.LocalStateManager()
        data = state.load()
        data['new'] = True
        with patch.object(Path, 'replace', side_effect=PermissionError('synthetic denial')):
            with self.assertRaises(self.manager.ProfileManagerError):
                state.save(data)
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), original)
        self.assertEqual(list(self.data.glob('.local-state-*')), [])

    def test_default_selection_uses_id_not_icon_or_name(self):
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.profiles = [('Default', 'Renamed default')]
        app.tree = Mock()
        app.tree.selection.return_value = ['row']
        app.tree.item.return_value = ('star or stale label', 'Default')
        self.assertEqual(app.get_selected_profile(), ('Default', 'Renamed default'))

    def test_multi_selection_disables_single_account_actions(self):
        app = self.fake_app([('Profile 1', 'A'), ('Profile 2', 'B')])
        app.update_account_buttons = Mock()
        app.on_select(None)
        self.assertIsNone(app.current_profile)

    def test_multi_open_continues_after_missing_profile(self):
        self.make_runtime()
        self.make_launch_profile('Profile 1')
        self.make_launch_profile('Profile 2')
        app = self.fake_app([('Profile 1', 'A'), ('Profile 404', 'Missing'), ('Profile 2', 'B')])
        with patch.object(self.manager.messagebox, 'showerror') as error:
            app.open_discord()
        self.assertEqual(self.popen.call_count, 2)
        self.assertIn('Profile 404', error.call_args.args[1])
        self.assertIn('failed: 1', app.update_status.call_args.args[0])
        roots = {call.args[0][1] for call in self.popen.call_args_list}
        self.assertEqual(len(roots), 2)

    def test_delete_cancellation_preserves_default_profile(self):
        self.make_launch_profile('Default')
        app = self.fake_app([('Default', 'Default')])
        with patch.object(self.manager.messagebox, 'askyesno', return_value=False):
            app.delete_profile()
        self.assertTrue((self.data / 'Default').is_dir())
        with patch.object(self.manager.messagebox, 'askyesno', return_value=True):
            app.delete_profile()
        self.assertEqual(self.manager.ProfileManager().get_profiles(), [])


if __name__ == '__main__':
    unittest.main()
