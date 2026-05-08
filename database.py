"""
Supabase database layer for TheChamp bot.

Each feature gets its own clearly marked section below.
To add a new feature, add functions under a new section header.

Required .env variables:
    SUPABASE_URL        — your project URL  (https://xxxx.supabase.co)
    SUPABASE_KEY        — service-role key  (Settings → API → service_role)

Supabase table setup — run this once in the SQL editor:

    CREATE TABLE shopping_list (
        id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        item      TEXT NOT NULL,
        added_at  TIMESTAMPTZ DEFAULT NOW(),
        bought    BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE todo_list (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        task       TEXT NOT NULL,
        due_date   DATE,
        done       BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
"""

import os
import logging
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY are not set. "
                "Add them to .env (local) or Railway Variables (deployed)."
            )
        _client = create_client(url, key)
        logger.info("Supabase client initialised")
    return _client


# ── Shopping list ──────────────────────────────────────────────────────────────

def add_shopping_items(items: list[str]) -> str:
    """Insert one or more items into the shopping list."""
    rows = [{"item": i.strip()} for i in items if i.strip()]
    if not rows:
        return "No items to add."
    try:
        get_client().table("shopping_list").insert(rows).execute()
        names = ", ".join(r["item"] for r in rows)
        logger.info("Added to shopping list: %s", names)
        return f"✅ Added: {names}"
    except Exception as exc:
        logger.error("add_shopping_items failed: %s", exc)
        return f"❌ Failed to add items: {exc}"


def get_shopping_list() -> str:
    """Return all unchecked items formatted for WhatsApp."""
    try:
        result = (
            get_client()
            .table("shopping_list")
            .select("item")
            .eq("bought", False)
            .order("added_at")
            .execute()
        )
        items = result.data
        if not items:
            return "🛒 Shopping list is empty!"
        lines = ["🛒 *Shopping list*", ""] + [f"{i+1}. {r['item']}" for i, r in enumerate(items)]
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_shopping_list failed: %s", exc)
        return f"❌ Couldn't fetch shopping list: {exc}"


def remove_shopping_item(item: str) -> str:
    """Mark matching items as bought (case-insensitive partial match)."""
    try:
        result = (
            get_client()
            .table("shopping_list")
            .update({"bought": True})
            .ilike("item", f"%{item.strip()}%")
            .eq("bought", False)
            .execute()
        )
        removed = result.data
        if not removed:
            return f"❌ '{item}' not found in the list."
        names = ", ".join(r["item"] for r in removed)
        logger.info("Removed from shopping list: %s", names)
        return f"✅ Removed: {names}"
    except Exception as exc:
        logger.error("remove_shopping_item failed: %s", exc)
        return f"❌ Failed to remove '{item}': {exc}"


def clear_shopping_list() -> str:
    """Delete all unchecked items from the shopping list."""
    try:
        result = (
            get_client()
            .table("shopping_list")
            .delete()
            .eq("bought", False)
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info("Cleared shopping list (%d items)", count)
        return f"🗑️ List cleared ({count} items removed)."
    except Exception as exc:
        logger.error("clear_shopping_list failed: %s", exc)
        return f"❌ Failed to clear list: {exc}"


# ── To-do list ─────────────────────────────────────────────────────────────────

def add_todo(task: str, due_date: str | None = None) -> str:
    """Insert a new task into the to-do list."""
    row: dict = {"task": task.strip()}
    if due_date:
        row["due_date"] = due_date
    try:
        get_client().table("todo_list").insert(row).execute()
        suffix = f" (due {due_date})" if due_date else ""
        logger.info("Added to-do: %s%s", task, suffix)
        return f"✅ Added: {task}{suffix}"
    except Exception as exc:
        logger.error("add_todo failed: %s", exc)
        return f"❌ Failed to add task: {exc}"


def get_todos() -> str:
    """Return all pending tasks formatted for WhatsApp."""
    try:
        result = (
            get_client()
            .table("todo_list")
            .select("task, due_date")
            .eq("done", False)
            .order("created_at")
            .execute()
        )
        items = result.data
        if not items:
            return "✅ To-do list is empty!"
        lines = ["📝 *To-do list*", ""]
        for i, r in enumerate(items):
            suffix = f" — due {r['due_date']}" if r.get("due_date") else ""
            lines.append(f"{i + 1}. {r['task']}{suffix}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_todos failed: %s", exc)
        return f"❌ Couldn't fetch to-do list: {exc}"


def complete_todo(task: str) -> str:
    """Mark matching tasks as done (case-insensitive partial match)."""
    try:
        result = (
            get_client()
            .table("todo_list")
            .update({"done": True})
            .ilike("task", f"%{task.strip()}%")
            .eq("done", False)
            .execute()
        )
        done = result.data
        if not done:
            return f"❌ '{task}' not found in the to-do list."
        names = ", ".join(r["task"] for r in done)
        logger.info("Completed to-do: %s", names)
        return f"✅ Done: {names}"
    except Exception as exc:
        logger.error("complete_todo failed: %s", exc)
        return f"❌ Failed to complete '{task}': {exc}"


def remove_todo(task: str) -> str:
    """Hard-delete a task from the to-do list (case-insensitive partial match)."""
    try:
        result = (
            get_client()
            .table("todo_list")
            .delete()
            .ilike("task", f"%{task.strip()}%")
            .execute()
        )
        removed = result.data
        if not removed:
            return f"❌ '{task}' not found in the to-do list."
        names = ", ".join(r["task"] for r in removed)
        logger.info("Removed to-do: %s", names)
        return f"🗑️ Removed: {names}"
    except Exception as exc:
        logger.error("remove_todo failed: %s", exc)
        return f"❌ Failed to remove '{task}': {exc}"


def get_todays_todos() -> list[dict]:
    """Return pending tasks due today or with no due date. Used by the morning briefing."""
    import datetime
    today = datetime.date.today().isoformat()
    try:
        due_today = (
            get_client()
            .table("todo_list")
            .select("task, due_date")
            .eq("done", False)
            .eq("due_date", today)
            .order("created_at")
            .execute()
        ).data
        no_due_date = (
            get_client()
            .table("todo_list")
            .select("task, due_date")
            .eq("done", False)
            .is_("due_date", "null")
            .order("created_at")
            .execute()
        ).data
        return due_today + no_due_date
    except Exception as exc:
        logger.error("get_todays_todos failed: %s", exc)
        return []
