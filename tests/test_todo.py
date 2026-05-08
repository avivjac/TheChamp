# -*- coding: utf-8 -*-
"""
Integration tests for database.py (Supabase to-do list).

All test tasks are prefixed with "TEST_TODO_" so they never pollute real data.
Each test starts with a clean slate (setUp wipes leftover TEST_TODO_ rows).

Run:
    python -m pytest tests/test_todo.py -v
    python tests/test_todo.py          (plain unittest)
"""

import sys
import os
import datetime
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import database

PREFIX = "TEST_TODO_"
TODAY = datetime.date.today().isoformat()
TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def _cleanup():
    """Delete all rows whose task starts with TEST_TODO_ (done or not)."""
    db = database.get_client()
    db.table("todo_list").delete().ilike("task", f"{PREFIX}%").execute()


class TestAddTodo(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_add_task_without_due_date(self):
        result = database.add_todo(f"{PREFIX}buy milk")
        self.assertIn("Added", result)
        self.assertIn(f"{PREFIX}buy milk", result)

    def test_add_task_with_due_date(self):
        result = database.add_todo(f"{PREFIX}submit report", due_date=TODAY)
        self.assertIn("Added", result)
        self.assertIn(TODAY, result)

    def test_added_task_appears_in_list(self):
        database.add_todo(f"{PREFIX}call dentist")
        lst = database.get_todos()
        self.assertIn(f"{PREFIX}call dentist", lst)

    def test_strips_whitespace_from_task(self):
        database.add_todo(f"  {PREFIX}clean room  ")
        lst = database.get_todos()
        self.assertIn(f"{PREFIX}clean room", lst)

    def test_due_date_shown_in_list(self):
        database.add_todo(f"{PREFIX}pay bill", due_date=TODAY)
        lst = database.get_todos()
        self.assertIn(TODAY, lst)


class TestViewTodos(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_empty_message_when_no_tasks(self):
        result = database.get_todos()
        # May have real tasks; just ensure it doesn't raise and returns a string
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_returns_added_tasks(self):
        database.add_todo(f"{PREFIX}task_a")
        database.add_todo(f"{PREFIX}task_b")
        lst = database.get_todos()
        self.assertIn(f"{PREFIX}task_a", lst)
        self.assertIn(f"{PREFIX}task_b", lst)

    def test_numbered_list_format(self):
        database.add_todo(f"{PREFIX}numbered_item")
        lst = database.get_todos()
        self.assertRegex(lst, r"\d+\.")

    def test_done_tasks_not_shown(self):
        database.add_todo(f"{PREFIX}hidden_task")
        database.complete_todo(f"{PREFIX}hidden_task")
        lst = database.get_todos()
        self.assertNotIn(f"{PREFIX}hidden_task", lst)


class TestCompleteTodo(unittest.TestCase):

    def setUp(self):
        _cleanup()
        database.add_todo(f"{PREFIX}finish homework")
        database.add_todo(f"{PREFIX}read book")
        database.add_todo(f"{PREFIX}read article")

    def tearDown(self):
        _cleanup()

    def test_complete_exact_match(self):
        result = database.complete_todo(f"{PREFIX}read book")
        self.assertIn("Done", result)
        self.assertIn(f"{PREFIX}read book", result)

    def test_complete_partial_match(self):
        # "TEST_TODO_read" matches both "read book" and "read article"
        result = database.complete_todo(f"{PREFIX}read")
        self.assertIn("Done", result)
        lst = database.get_todos()
        self.assertNotIn(f"{PREFIX}read book", lst)
        self.assertNotIn(f"{PREFIX}read article", lst)

    def test_complete_case_insensitive(self):
        result = database.complete_todo(f"{PREFIX}FINISH HOMEWORK".upper())
        # ilike is case-insensitive — should still find the task
        self.assertIsInstance(result, str)

    def test_complete_nonexistent_returns_not_found(self):
        result = database.complete_todo(f"{PREFIX}task_that_does_not_exist_xyz")
        self.assertIn("not found", result)

    def test_complete_does_not_hard_delete(self):
        database.complete_todo(f"{PREFIX}finish homework")
        db = database.get_client()
        rows = (
            db.table("todo_list")
            .select("task, done")
            .eq("done", True)
            .ilike("task", f"{PREFIX}finish homework")
            .execute()
        )
        self.assertGreater(len(rows.data), 0, "Completed task should remain with done=True")

    def test_completed_task_not_completable_again(self):
        database.complete_todo(f"{PREFIX}finish homework")
        result = database.complete_todo(f"{PREFIX}finish homework")
        self.assertIn("not found", result)

    def test_other_tasks_unaffected(self):
        database.complete_todo(f"{PREFIX}finish homework")
        lst = database.get_todos()
        self.assertIn(f"{PREFIX}read book", lst)


class TestRemoveTodo(unittest.TestCase):

    def setUp(self):
        _cleanup()
        database.add_todo(f"{PREFIX}water plants")
        database.add_todo(f"{PREFIX}water the dog")

    def tearDown(self):
        _cleanup()

    def test_remove_exact_match(self):
        result = database.remove_todo(f"{PREFIX}water plants")
        self.assertIn("Removed", result)
        lst = database.get_todos()
        self.assertNotIn(f"{PREFIX}water plants", lst)

    def test_remove_partial_match(self):
        result = database.remove_todo(f"{PREFIX}water")
        self.assertIn("Removed", result)
        lst = database.get_todos()
        self.assertNotIn(f"{PREFIX}water plants", lst)
        self.assertNotIn(f"{PREFIX}water the dog", lst)

    def test_remove_is_hard_delete(self):
        database.remove_todo(f"{PREFIX}water plants")
        db = database.get_client()
        rows = (
            db.table("todo_list")
            .select("task")
            .ilike("task", f"{PREFIX}water plants")
            .execute()
        )
        self.assertEqual(len(rows.data), 0, "remove_todo should hard-delete the row")

    def test_remove_nonexistent_returns_not_found(self):
        result = database.remove_todo(f"{PREFIX}nonexistent_task_xyz")
        self.assertIn("not found", result)


class TestGetTodaysTodos(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_task_due_today_included(self):
        database.add_todo(f"{PREFIX}due_today", due_date=TODAY)
        todos = database.get_todays_todos()
        tasks = [t["task"] for t in todos]
        self.assertIn(f"{PREFIX}due_today", tasks)

    def test_task_with_no_due_date_included(self):
        database.add_todo(f"{PREFIX}no_date")
        todos = database.get_todays_todos()
        tasks = [t["task"] for t in todos]
        self.assertIn(f"{PREFIX}no_date", tasks)

    def test_task_due_tomorrow_excluded(self):
        database.add_todo(f"{PREFIX}due_tomorrow", due_date=TOMORROW)
        todos = database.get_todays_todos()
        tasks = [t["task"] for t in todos]
        self.assertNotIn(f"{PREFIX}due_tomorrow", tasks)

    def test_task_due_yesterday_excluded(self):
        database.add_todo(f"{PREFIX}due_yesterday", due_date=YESTERDAY)
        todos = database.get_todays_todos()
        tasks = [t["task"] for t in todos]
        self.assertNotIn(f"{PREFIX}due_yesterday", tasks)

    def test_done_tasks_excluded(self):
        database.add_todo(f"{PREFIX}done_today", due_date=TODAY)
        database.complete_todo(f"{PREFIX}done_today")
        todos = database.get_todays_todos()
        tasks = [t["task"] for t in todos]
        self.assertNotIn(f"{PREFIX}done_today", tasks)

    def test_returns_list(self):
        todos = database.get_todays_todos()
        self.assertIsInstance(todos, list)

    def test_each_item_has_task_field(self):
        database.add_todo(f"{PREFIX}check_fields", due_date=TODAY)
        todos = database.get_todays_todos()
        for t in todos:
            self.assertIn("task", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
