"""M4 application-owned profile metadata tests using disposable data."""

import json
import shutil
import unittest
from unittest.mock import patch

import test_m1_runtime as m1


class MetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    setUp = m1.RuntimeTests.setUp
    cleanup_workspace = m1.RuntimeTests.cleanup_workspace
    make_runtime = m1.RuntimeTests.make_runtime
    make_profiles = m1.RuntimeTests.make_profiles
    make_launch_profile = m1.RuntimeTests.make_launch_profile

    def read_metadata(self):
        return json.loads(self.manager.PROFILES_JSON.read_text(encoding='utf-8'))

    def write_metadata(self, data):
        self.manager.PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
        self.manager.PROFILES_JSON.write_text(json.dumps(data), encoding='utf-8')

    def test_startup_without_profiles_json_creates_empty_catalog(self):
        profiles = self.manager.ProfileManager()
        profiles.initialize_metadata()

        self.assertEqual(profiles.get_profiles(), [])
        self.assertEqual(self.read_metadata(), {'version': 1, 'profiles': []})

    def test_existing_managed_profile_is_discovered_without_registry_record(self):
        directory = self.profiles / 'profile_0007' / 'Default'
        directory.mkdir(parents=True)
        preferences = directory / 'Preferences'
        preferences.write_text('{"fixture": true}', encoding='utf-8')

        profiles = self.manager.ProfileManager()
        self.assertEqual(profiles.get_profiles(), [('profile_0007', 'profile_0007')])
        self.assertEqual(preferences.read_text(encoding='utf-8'), '{"fixture": true}')
        self.assertEqual(self.read_metadata()['profiles'][0]['profile_directory'], 'profiles/profile_0007')

    def test_legacy_profile_is_imported_into_application_metadata(self):
        legacy = self.make_launch_profile('Profile 1')
        original = (legacy / 'Default' / 'Preferences').read_bytes()

        profiles = self.manager.ProfileManager()
        records = profiles.get_profile_metadata()
        self.assertEqual(records[0]['profile_id'], 'Profile 1')
        self.assertEqual(records[0]['profile_directory'], 'legacy/data/Profile 1')
        self.assertEqual((legacy / 'Default' / 'Preferences').read_bytes(), original)

    def test_profile_creation_publishes_required_metadata(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile('M4 Created')
        record = profiles.get_profile_metadata()[0]

        self.assertEqual(record['profile_id'], profile_id)
        self.assertEqual(record['display_name'], 'M4 Created')
        self.assertEqual(record['profile_directory'], f'profiles/{profile_id}')
        self.assertIsNotNone(record['created_at'])
        self.assertIsNone(record['last_opened_at'])
        self.assertEqual(record['environment_preset'], 'default')
        self.assertFalse(record['proxy_enabled'])
        self.assertTrue((self.profiles / profile_id / 'Default' / 'Preferences').is_file())

    def test_metadata_persists_after_manager_restart(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile('Persistent')
        restarted = self.manager.ProfileManager()

        self.assertEqual(restarted.get_profiles(), [(profile_id, 'Persistent')])
        self.assertEqual(restarted.get_profile_metadata()[0]['profile_id'], profile_id)

    def test_rename_changes_display_name_without_renaming_physical_directory(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile('Before')
        directory = profiles.get_profile_dir(profile_id)

        profiles.rename_profile(profile_id, 'After')

        self.assertEqual(profiles.get_profiles(), [(profile_id, 'After')])
        self.assertTrue(directory.is_dir())
        self.assertFalse((self.profiles / 'After').exists())

    def test_open_updates_last_opened_at_and_keeps_profile_data(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile('Open me')
        marker = profiles.get_profile_dir(profile_id) / 'Default' / 'keep.fixture'
        marker.write_bytes(b'profile data')

        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id))

        record = self.manager.ProfileManager().get_profile_metadata()[0]
        self.assertIsNotNone(record['last_opened_at'])
        self.assertEqual(marker.read_bytes(), b'profile data')

    def test_multiple_profiles_have_independent_metadata_records(self):
        profiles = self.make_profiles()
        first = profiles.create_profile('First')
        second = profiles.create_profile('Second')

        records = {record['profile_id']: record for record in profiles.get_profile_metadata()}
        self.assertEqual(set(records), {first, second})
        self.assertNotEqual(records[first]['profile_directory'], records[second]['profile_directory'])

    def test_multi_open_keeps_profiles_json_valid(self):
        self.make_runtime()
        profiles = self.make_profiles()
        first = profiles.create_profile('First')
        second = profiles.create_profile('Second')
        launcher = self.manager.ChromiumLauncher()

        self.assertTrue(launcher.launch_discord(first))
        self.assertTrue(launcher.launch_discord(second))
        catalog = self.read_metadata()
        self.assertEqual(len(catalog['profiles']), 2)
        self.assertTrue(all(record['last_opened_at'] for record in catalog['profiles']))

    def test_malformed_json_is_preserved_and_does_not_delete_profiles(self):
        physical = self.profiles / 'profile_0001' / 'Default'
        physical.mkdir(parents=True)
        (physical / 'Preferences').write_text('{}', encoding='utf-8')
        raw = b'{broken'
        self.manager.PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
        self.manager.PROFILES_JSON.write_bytes(raw)

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().get_profiles()
        self.assertEqual(self.manager.PROFILES_JSON.read_bytes(), raw)
        self.assertTrue(physical.is_dir())

    def test_partially_malformed_record_is_preserved(self):
        raw = {
            'version': 1,
            'profiles': [
                {
                    'profile_id': 'profile_0001',
                    'display_name': 'Valid',
                    'profile_directory': 'profiles/profile_0001',
                    'created_at': '2026-01-01T00:00:00Z',
                    'last_opened_at': None,
                    'environment_preset': 'default',
                    'proxy_enabled': False,
                },
                {'profile_id': 'broken'},
            ],
        }
        original = json.dumps(raw).encode('utf-8')
        self.manager.PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
        self.manager.PROFILES_JSON.write_bytes(original)

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().get_profiles()
        self.assertEqual(self.manager.PROFILES_JSON.read_bytes(), original)

    def test_duplicate_profile_ids_are_rejected_without_rewrite(self):
        record = {
            'profile_id': 'profile_0001', 'display_name': 'One',
            'profile_directory': 'profiles/profile_0001',
            'created_at': '2026-01-01T00:00:00Z', 'last_opened_at': None,
            'environment_preset': 'default', 'proxy_enabled': False,
        }
        raw = {'version': 1, 'profiles': [record, {**record, 'display_name': 'Two'}]}
        self.write_metadata(raw)
        original = self.manager.PROFILES_JSON.read_bytes()

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().get_profiles()
        self.assertEqual(self.manager.PROFILES_JSON.read_bytes(), original)

    def test_duplicate_profile_directory_mappings_are_rejected(self):
        def record(profile_id, directory):
            return {
                'profile_id': profile_id, 'display_name': profile_id,
                'profile_directory': directory,
                'created_at': '2026-01-01T00:00:00Z', 'last_opened_at': None,
                'environment_preset': 'default', 'proxy_enabled': False,
            }
        self.write_metadata({'version': 1, 'profiles': [
            record('A', 'profiles/profile_0001'),
            record('B', 'profiles/PROFILE_0001'),
        ]})

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().get_profiles()

    def test_missing_directory_remains_metadata_only_and_is_not_recreated(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile('Missing later')
        directory = profiles.get_profile_dir(profile_id)
        shutil.rmtree(directory)

        with self.assertRaises(self.manager.ProfileManagerError):
            profiles.require_profile_dir(profile_id)
        self.assertFalse(directory.exists())
        self.assertEqual(profiles.get_profiles(), [(profile_id, 'Missing later')])

    def test_managed_physical_directory_missing_from_catalog_is_imported(self):
        profiles = self.make_profiles()
        profiles.create_profile('Known')
        orphan = self.profiles / 'profile_0099' / 'Default'
        orphan.mkdir(parents=True)
        (orphan / 'Preferences').write_text('{}', encoding='utf-8')

        records = profiles.get_profile_metadata()
        self.assertEqual({record['profile_id'] for record in records}, {'profile_0001', 'profile_0099'})
        self.assertTrue((self.profiles / 'profile_0099').is_dir())

    def test_empty_metadata_file_is_initialized_without_touching_profiles(self):
        physical = self.profiles / 'profile_0004' / 'Default'
        physical.mkdir(parents=True)
        (physical / 'Preferences').write_text('{}', encoding='utf-8')
        self.manager.PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
        self.manager.PROFILES_JSON.write_bytes(b'')

        self.assertEqual(self.manager.ProfileManager().get_profiles(), [('profile_0004', 'profile_0004')])
        self.assertTrue((physical / 'Preferences').is_file())
        self.assertTrue(self.manager.PROFILES_JSON.read_bytes())

    def test_atomic_metadata_replace_preserves_original_on_failure(self):
        profiles = self.make_profiles()
        profiles.create_profile('Atomic')
        original = self.manager.PROFILES_JSON.read_bytes()
        catalog = profiles.metadata.load()
        catalog['profiles'][0]['display_name'] = 'Changed'

        with patch.object(self.manager.Path, 'replace', side_effect=PermissionError('synthetic denial')):
            with self.assertRaises(self.manager.ProfileManagerError):
                profiles.metadata.save(catalog)
        self.assertEqual(self.manager.PROFILES_JSON.read_bytes(), original)
        self.assertEqual(list(self.manager.PROFILES_JSON.parent.glob('.profiles-*.tmp')), [])

    def test_migrated_m3_profile_remains_recognized(self):
        source = self.make_launch_profile('Profile 1')
        profiles = self.manager.ProfileManager()
        managed_id = profiles.migrate_profile('Profile 1')
        restarted = self.manager.ProfileManager()

        record = next(item for item in restarted.get_profile_metadata() if item['profile_id'] == 'Profile 1')
        self.assertEqual(record['profile_directory'], f'profiles/{managed_id}')
        self.assertTrue(source.is_dir())
        self.assertTrue((self.profiles / managed_id).is_dir())

    def test_sensitive_fields_are_not_accepted_in_profiles_json(self):
        record = {
            'profile_id': 'profile_0001', 'display_name': 'No secrets',
            'profile_directory': 'profiles/profile_0001',
            'created_at': '2026-01-01T00:00:00Z', 'last_opened_at': None,
            'environment_preset': 'default', 'proxy_enabled': False,
            'password': 'synthetic-password',
        }
        self.write_metadata({'version': 1, 'profiles': [record]})

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().get_profiles()


if __name__ == '__main__':
    unittest.main()
