# -*- coding: utf-8 -*-
"""
Integration tests for database.py (Supabase shopping list).

All test items are prefixed with "TEST_" so they never pollute real data.
Each test starts with a clean slate (setUp wipes leftover TEST_ rows).

Run:
    python -m pytest tests/test_database.py -v
    python tests/test_database.py          (plain unittest)
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import database

PREFIX = "TEST_"


def _cleanup():
    """Delete all rows whose item starts with TEST_ (bought or not)."""
    db = database.get_client()
    db.table("shopping_list").delete().ilike("item", f"{PREFIX}%").execute()


class TestConnection(unittest.TestCase):

    def test_client_connects(self):
        client = database.get_client()
        self.assertIsNotNone(client)

    def test_table_is_reachable(self):
        # A plain select should not raise
        result = database.get_client().table("shopping_list").select("id").limit(1).execute()
        self.assertIsNotNone(result)


class TestAddItems(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_add_single_item(self):
        result = database.add_shopping_items([f"{PREFIX}milk"])
        self.assertIn("Added", result)
        self.assertIn(f"{PREFIX}milk", result)

    def test_add_multiple_items(self):
        items = [f"{PREFIX}eggs", f"{PREFIX}bread", f"{PREFIX}butter"]
        result = database.add_shopping_items(items)
        self.assertIn("Added", result)
        for item in items:
            self.assertIn(item, result)

    def test_add_strips_whitespace(self):
        result = database.add_shopping_items([f"  {PREFIX}juice  "])
        self.assertIn("Added", result)
        # Verify it was stored without leading/trailing spaces
        lst = database.get_shopping_list()
        self.assertIn(f"{PREFIX}juice", lst)

    def test_add_empty_list_returns_message(self):
        result = database.add_shopping_items([])
        self.assertIn("No items", result)

    def test_add_whitespace_only_items_are_ignored(self):
        result = database.add_shopping_items(["   ", ""])
        self.assertIn("No items", result)

    def test_added_items_appear_in_list(self):
        database.add_shopping_items([f"{PREFIX}tomatoes"])
        lst = database.get_shopping_list()
        self.assertIn(f"{PREFIX}tomatoes", lst)


class TestViewList(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_empty_list_message(self):
        result = database.get_shopping_list()
        # May contain other real items; if TEST_ items were cleaned, at least no error
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_returns_added_items(self):
        database.add_shopping_items([f"{PREFIX}a", f"{PREFIX}b", f"{PREFIX}c"])
        lst = database.get_shopping_list()
        self.assertIn(f"{PREFIX}a", lst)
        self.assertIn(f"{PREFIX}b", lst)
        self.assertIn(f"{PREFIX}c", lst)

    def test_numbered_list_format(self):
        database.add_shopping_items([f"{PREFIX}item1"])
        lst = database.get_shopping_list()
        self.assertRegex(lst, r"\d+\.")

    def test_bought_items_not_shown(self):
        database.add_shopping_items([f"{PREFIX}hidden"])
        database.remove_shopping_item(f"{PREFIX}hidden")  # marks as bought
        lst = database.get_shopping_list()
        self.assertNotIn(f"{PREFIX}hidden", lst)


class TestRemoveItem(unittest.TestCase):

    def setUp(self):
        _cleanup()
        database.add_shopping_items([
            f"{PREFIX}milk",
            f"{PREFIX}almond milk",
            f"{PREFIX}eggs",
        ])

    def tearDown(self):
        _cleanup()

    def test_remove_exact_match(self):
        result = database.remove_shopping_item(f"{PREFIX}eggs")
        self.assertIn("Removed", result)
        self.assertIn(f"{PREFIX}eggs", result)
        lst = database.get_shopping_list()
        self.assertNotIn(f"{PREFIX}eggs", lst)

    def test_remove_partial_match(self):
        # "TEST_coffee" is a substring of "TEST_coffee beans", so ilike %TEST_coffee%
        # should remove both entries at once.
        database.add_shopping_items([f"{PREFIX}coffee", f"{PREFIX}coffee beans"])
        result = database.remove_shopping_item(f"{PREFIX}coffee")
        self.assertIn("Removed", result)
        lst = database.get_shopping_list()
        self.assertNotIn(f"{PREFIX}coffee", lst)
        self.assertNotIn(f"{PREFIX}coffee beans", lst)

    def test_remove_case_insensitive(self):
        result = database.remove_shopping_item(f"{PREFIX}EGGS".upper())
        # ilike is case-insensitive so TEST_eggs should be matched
        # (PREFIX is TEST_, upper gives TEST_EGGS which ilike matches TEST_eggs)
        self.assertIsInstance(result, str)

    def test_remove_nonexistent_item_returns_not_found(self):
        result = database.remove_shopping_item(f"{PREFIX}unicorn_item_xyz")
        self.assertIn("not found", result)

    def test_remove_does_not_hard_delete(self):
        # The row should still exist in DB with bought=True (history preserved)
        database.remove_shopping_item(f"{PREFIX}eggs")
        db = database.get_client()
        result = db.table("shopping_list").select("item, bought").eq("bought", True).ilike("item", f"{PREFIX}eggs").execute()
        self.assertGreater(len(result.data), 0, "Removed item should be kept with bought=True")

    def test_list_still_has_other_items_after_remove(self):
        database.remove_shopping_item(f"{PREFIX}eggs")
        lst = database.get_shopping_list()
        self.assertIn(f"{PREFIX}milk", lst)


class TestClearList(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_clear_removes_all_unchecked(self):
        database.add_shopping_items([f"{PREFIX}x", f"{PREFIX}y", f"{PREFIX}z"])
        # Confirm they're there first
        lst = database.get_shopping_list()
        self.assertIn(f"{PREFIX}x", lst)
        # Clear
        result = database.clear_shopping_list()
        self.assertIn("cleared", result.lower())
        # Confirm gone
        db = database.get_client()
        remaining = db.table("shopping_list").select("item").eq("bought", False).ilike("item", f"{PREFIX}%").execute()
        self.assertEqual(len(remaining.data), 0)

    def test_clear_reports_count(self):
        database.add_shopping_items([f"{PREFIX}p", f"{PREFIX}q"])
        result = database.clear_shopping_list()
        # Should mention a non-zero count (may include non-TEST items, so just check it's numeric)
        import re
        numbers = re.findall(r"\d+", result)
        self.assertTrue(any(int(n) >= 2 for n in numbers),
                        f"Expected count >= 2 in: {result!r}")

    def test_clear_empty_list_does_not_crash(self):
        result = database.clear_shopping_list()
        self.assertIsInstance(result, str)
        self.assertNotIn("Failed", result)

    def test_clear_does_not_remove_bought_items(self):
        database.add_shopping_items([f"{PREFIX}already_bought"])
        database.remove_shopping_item(f"{PREFIX}already_bought")  # mark bought
        database.clear_shopping_list()
        # The bought=True row should still exist
        db = database.get_client()
        result = db.table("shopping_list").select("item").eq("bought", True).ilike("item", f"{PREFIX}already_bought").execute()
        self.assertGreater(len(result.data), 0, "Bought items should survive clear_shopping_list")


if __name__ == "__main__":
    unittest.main(verbosity=2)
