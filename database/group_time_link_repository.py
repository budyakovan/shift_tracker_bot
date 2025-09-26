# -*- coding: utf-8 -*-
import logging
from contextlib import contextmanager
from typing import Optional, Dict

from database.connection import db_connection

logger = logging.getLogger(__name__)

@contextmanager
def _cursor():
    if hasattr(db_connection, "get_connection"):
        conn = db_connection.get_connection()
    elif hasattr(db_connection, "connect"):
        conn = db_connection.connect()
    elif hasattr(db_connection, "connection"):
        conn = db_connection.connection()
    else:
        raise RuntimeError("db_connection: нет метода get_connection/connect/connection")
    cur = None
    try:
        cur = conn.cursor()
        yield conn, cur
        try: conn.commit()
        except Exception: pass
    except Exception:
        try: conn.rollback()
        except Exception: pass
        raise
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass

def set_link(group_key: str, time_group_key: str) -> None:
    sql = """
        INSERT INTO group_time_link (group_key, time_group_key)
        VALUES (%s, %s)
        ON CONFLICT (group_key)
        DO UPDATE SET time_group_key=EXCLUDED.time_group_key, linked_at=NOW()
    """
    with _cursor() as (conn, cur):
        cur.execute(sql, (group_key, time_group_key))

def remove_link(group_key: str) -> bool:
    sql = "DELETE FROM group_time_link WHERE group_key=%s"
    with _cursor() as (conn, cur):
        cur.execute(sql, (group_key,))
        return cur.rowcount > 0

def get_link(group_key: str) -> Optional[str]:
    sql = "SELECT time_group_key FROM group_time_link WHERE group_key=%s"
    with _cursor() as (conn, cur):
        cur.execute(sql, (group_key,))
        row = cur.fetchone()
        return row[0] if row else None

def find_by_time_group(time_group_key: str) -> Optional[Dict]:
    sql = "SELECT group_key, time_group_key, linked_at FROM group_time_link WHERE time_group_key=%s"
    with _cursor() as (conn, cur):
        cur.execute(sql, (time_group_key,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(group_key=row[0], time_group_key=row[1], linked_at=row[2])
