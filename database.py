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
"""

import os
import logging
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
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
