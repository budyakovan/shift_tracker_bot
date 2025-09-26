
# -*- coding: utf-8 -*-
"""Repository layer for the duty catalog (table: duty)."""
from typing import List, Optional, Dict, Any
import psycopg2.extras
from .connection import db_connection

def _row_to_dict(row) -> Dict[str, Any]:
    return {
        "key": row["key"],
        "title": row["title"],
        "weight": row["weight"],
        "office_required": bool(row["office_required"]),
        "target_rank": row["target_rank"],
        "min_rank": row["min_rank"],
        "description": row["description"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }

def fetch_catalog(search: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    conn = db_connection.get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        if search:
            cur.execute(
                """
                SELECT key, title, weight, office_required, target_rank, min_rank, description, is_active, created_at
                FROM duty
                WHERE is_active = TRUE
                  AND (key ILIKE %s OR title ILIKE %s OR COALESCE(description, '') ILIKE %s)
                ORDER BY key
                LIMIT %s
                """,
                (f"%{search}%", f"%{search}%", f"%{search}%", limit),
            )
        else:
            cur.execute(
                """
                SELECT key, title, weight, office_required, target_rank, min_rank, description, is_active, created_at
                FROM duty
                WHERE is_active = TRUE
                ORDER BY key
                LIMIT %s
                """,
                (limit,),
            )
        return [_row_to_dict(r) for r in cur.fetchall()]

def get_by_key(key: str) -> Optional[Dict[str, Any]]:
    conn = db_connection.get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            """
            SELECT key, title, weight, office_required, target_rank, min_rank, description, is_active, created_at
            FROM duty WHERE key=%s
            """, (key,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

def set_active(key: str, is_active: bool) -> bool:
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE duty SET is_active=%s WHERE key=%s", (is_active, key))
        conn.commit()
        return cur.rowcount > 0

def upsert_duty(data: Dict[str, Any]) -> str:
    """Insert or update one duty by key. Returns the key."""
    key = str(data.get("key") or "").strip()
    if not key:
        raise ValueError("key is required")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    weight = int(data.get("weight") or 10)
    office_required = bool(int(data.get("office_required") or 0))
    target_rank = data.get("target_rank")
    min_rank = data.get("min_rank")
    description = (data.get("description") or "").strip()
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO duty (key, title, description, weight, office_required, target_rank, min_rank, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)
            ON CONFLICT (key) DO UPDATE SET
              title=EXCLUDED.title,
              description=EXCLUDED.description,
              weight=EXCLUDED.weight,
              office_required=EXCLUDED.office_required,
              target_rank = COALESCE(EXCLUDED.target_rank, duty.target_rank),
              min_rank    = COALESCE(EXCLUDED.min_rank, duty.min_rank),
              is_active=TRUE
            """,
            (key, title, description, weight, office_required, target_rank, min_rank),
        )
        conn.commit()
    return key

def delete_by_key(key: str) -> bool:
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM duty WHERE key=%s", (key,))
        conn.commit()
        return cur.rowcount > 0
