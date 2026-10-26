"""Table STT is the 1-based position in table order: the list is sorted first and numbered second."""

import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped.main import compose_product_candidate
from revamped.processes import ChromiumProcessInspector
from revamped.product_api import ProductAPI
from revamped.profiles import profile_display_sort_key, table_order


# Created in this order, so profile IDs are profile_0001..profile_0019. The two deletions leave ID gaps. The typed
# numbers have gaps, "0059" appears twice, and "gamma 42 [FLAG]" is a FLAG name whose number is not its position.
CREATED_NAMES = [
    "Profile 64",          # profile_0001
    "0002 | beta",         # profile_0002
    "[FLAG] alpha",        # profile_0003
    "zulu",                # profile_0004
    "0010 | gamma",        # profile_0005, deleted
    "Profile 5",           # profile_0006
    "0001 | alpha",        # profile_0007
    "delta (FLAG)",        # profile_0008
    "Profile 109",         # profile_0009
    "0059 | first",        # profile_0010
    "0059 | second",       # profile_0011
    "eta",                 # profile_0012, deleted
    "Profile 12",          # profile_0013
    "[flag] omega",        # profile_0014
    "0004 | FLAG tagged",  # profile_0015
    "Profile 64 [FLAG]",   # profile_0016
    "gamma 42 [FLAG]",     # profile_0017
    "plain zeta",          # profile_0018, plain despite being created after FLAG/default names
    "plain alpha",         # profile_0019, plain order follows catalog order, not alphabetic order
]
DELETED_NAMES = ("0010 | gamma", "eta")
EXPECTED_ORDER = [
    # 1. Typed numbers, ascending. Equal numbers keep catalog order.
    "0001 | alpha",
    "0002 | beta",
    "0004 | FLAG tagged",
    "0059 | first",
    "0059 | second",
    # 2. Plain account names keep catalog order, including names created after FLAG/default names.
    "zulu",
    "plain zeta",
    "plain alpha",
    # 3. FLAG names, by profile number. "Profile 64 [FLAG]" is FLAG, not default.
    "[FLAG] alpha",
    "delta (FLAG)",
    "[flag] omega",
    "Profile 64 [FLAG]",
    "gamma 42 [FLAG]",
    # 4. Default "Profile N" names, ascending by N.
    "Profile 5",
    "Profile 12",
    "Profile 64",
    "Profile 109",
]
EXPECTED_STT = [f"{position:04d}" for position in range(1, len(EXPECTED_ORDER) + 1)]


class DisplayOrderTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("display-order-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.application = compose_product_candidate(
            self.workspace.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )
        self.profiles = self.application.profile_service
        self.profiles.initialize_metadata()
        self.api = ProductAPI(self.application)
        self.addCleanup(self.api.shutdown)
        self.created = {name: self.profiles.create_profile(name) for name in CREATED_NAMES}
        self.profiles.delete_profiles([self.created[name] for name in DELETED_NAMES])

    def test_stt_is_one_to_n_over_the_sorted_order(self):
        rows = self.api.list_profiles()
        stts = [int(row["stt"]) for row in rows]

        self.assertEqual([row["name"] for row in rows], EXPECTED_ORDER)
        self.assertEqual([row["stt"] for row in rows], EXPECTED_STT)
        self.assertEqual(stts, list(range(1, len(EXPECTED_ORDER) + 1)), "STT must have no gaps")
        self.assertTrue(all(left < right for left, right in zip(stts, stts[1:])), "STT must strictly increase")
        self.assertEqual(len(set(stts)), len(stts), "STT must not repeat")

    def test_numbers_in_names_are_never_used_as_stt(self):
        stt_by_name = {row["name"]: row["stt"] for row in self.api.list_profiles()}

        self.assertEqual(stt_by_name["0004 | FLAG tagged"], "0003")
        self.assertEqual(stt_by_name["0059 | first"], "0004")
        self.assertEqual(stt_by_name["gamma 42 [FLAG]"], "0013")
        self.assertEqual(stt_by_name["Profile 109"], "0017")
        self.assertEqual(stt_by_name["zulu"], "0006")

    def test_plain_names_created_after_flag_and_default_names_keep_catalog_order(self):
        names = [row["name"] for row in self.api.list_profiles()]

        self.assertEqual(names[5:8], ["zulu", "plain zeta", "plain alpha"])
        self.assertLess(names.index("plain zeta"), names.index("[FLAG] alpha"))
        self.assertLess(names.index("plain alpha"), names.index("Profile 5"))

    def test_changing_a_number_inside_a_flag_name_keeps_every_stt(self):
        before = {row["profile_id"]: row["stt"] for row in self.api.list_profiles()}

        self.api.update_profile(self.created["gamma 42 [FLAG]"], name="gamma 99 [FLAG]")

        self.assertEqual({row["profile_id"]: row["stt"] for row in self.api.list_profiles()}, before)

    def test_create_and_delete_renumber_the_whole_table_and_arrange_reads_the_same_stt(self):
        created = self.api.create_profile("0100 | late")
        rows = self.api.list_profiles()

        self.assertEqual(created["stt"], "0006")
        self.assertEqual(rows[5]["name"], "0100 | late")
        self.assertEqual([int(row["stt"]) for row in rows], list(range(1, 19)))

        self.api.delete_profiles([self.created["0001 | alpha"]], confirmed=True)
        rows = self.api.list_profiles()

        self.assertEqual([int(row["stt"]) for row in rows], list(range(1, 18)))
        for row in rows:
            self.assertEqual(self.profiles.display_position(row["profile_id"]), int(row["stt"]))

    def test_display_order_and_delta_rows_carry_the_same_stt_as_the_list(self):
        listed = [(row["profile_id"], row["stt"]) for row in self.api.list_profiles()]

        self.assertEqual([(row["profile_id"], row["stt"]) for row in self.api.display_order()], listed)
        created = self.api.create_profile("0003 | late")
        stt_by_id = {row["profile_id"]: row["stt"] for row in self.api.display_order()}
        self.assertEqual(created["stt"], stt_by_id[created["profile_id"]])

    def test_sorting_by_another_column_changes_only_the_row_order(self):
        default_stt = {row["profile_id"]: row["stt"] for row in self.api.list_profiles()}

        by_name = self.api.list_profiles(sort="name")

        self.assertEqual({row["profile_id"]: row["stt"] for row in by_name}, default_stt)
        self.assertEqual([row["name"] for row in by_name], sorted(EXPECTED_ORDER, key=str.casefold))

    def test_sort_key_patterns(self):
        cases = {
            "0001 | name": (0, 1),
            "  0007|name": (0, 7),
            "0004 | FLAG tagged": (0, 4),
            "[FLAG] name": (2, 42),
            "name (flag)": (2, 42),
            "Profile 64 [FLAG]": (2, 42),
            "Profile 64": (3, 64),
            "Profile 64 ": (3, 64),
            "profile 64": (1, 0),
            "Profile 64a": (1, 0),
            "zulu": (1, 0),
            "": (1, 0),
            None: (1, 0),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(profile_display_sort_key(name, "profile_0042"), expected)

    def test_all_four_groups_keep_their_policy_and_continuous_stt(self):
        records = [
            {"profile_id": "profile_0008", "display_name": "Profile 12"},
            {"profile_id": "profile_0003", "display_name": "[FLAG] tagged"},
            {"profile_id": "profile_0007", "display_name": "plain second"},
            {"profile_id": "profile_0006", "display_name": "0002 | second"},
            {"profile_id": "profile_0002", "display_name": "Profile 5"},
            {"profile_id": "profile_0001", "display_name": "plain first"},
            {"profile_id": "profile_0004", "display_name": "0001 | first"},
            {"profile_id": "profile_0005", "display_name": "name (FLAG)"},
        ]

        ordered = table_order(records)

        self.assertEqual([stt for stt, _ in ordered], list(range(1, 9)))
        self.assertEqual(
            [record["profile_id"] for _, record in ordered],
            [
                "profile_0004", "profile_0006",  # prefixed, numeric order
                "profile_0007", "profile_0001",  # plain, catalog order
                "profile_0003", "profile_0005",  # FLAG, profile number order
                "profile_0002", "profile_0008",  # default Profile N, numeric order
            ],
        )


if __name__ == "__main__":
    unittest.main()
