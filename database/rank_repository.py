# /home/telegrambot/shift_tracker_bot/database/rank_repository.py
# -*- coding: utf-8 -*-
"""
Репозиторий для работы с дополнительными данными дежурств:
- Ранги участников (веса для алгоритма распределения)
- Исключения из дежурств (временные периоды когда пользователь не доступен)
- Round-robin курсоры (последние назначения для циклического распределения)
"""

from typing import Optional, Dict, Any, List
import logging
from .connection import db_connection

logger = logging.getLogger(__name__)

# ---- RANKS ----
def set_member_rank(group_key: str, user_id: int, rank: int, admin_id: Optional[int]) -> bool:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            INSERT INTO member_ranks (group_key, user_id, rank, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (group_key, user_id) DO UPDATE
              SET rank=EXCLUDED.rank, updated_by=EXCLUDED.updated_by, updated_at=NOW()
        """, (group_key, user_id, rank, admin_id))
        db_connection.get_connection().commit()
        return True

def get_member_rank(group_key: str, user_id: int) -> Optional[int]:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("SELECT rank FROM member_ranks WHERE group_key=%s AND user_id=%s", (group_key, user_id))
        row = cur.fetchone()
        return int(row[0]) if row else None

def list_member_ranks(group_key: str) -> List[Dict[str, Any]]:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            SELECT user_id, rank, updated_by, updated_at
            FROM member_ranks
            WHERE group_key=%s
            ORDER BY user_id
        """, (group_key,))
        return [{"user_id": r[0], "rank": r[1], "updated_by": r[2], "updated_at": r[3]} for r in cur.fetchall()]


# ---- RR CURSOR ----
def get_rr_last(group_key: str, duty_id: int) -> Optional[int]:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("SELECT last_user_id FROM duty_rr_cursor WHERE group_key=%s AND duty_id=%s", (group_key, duty_id))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

def set_rr_last(group_key: str, duty_id: int, user_id: int) -> None:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            INSERT INTO duty_rr_cursor (group_key, duty_id, last_user_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (group_key, duty_id) DO UPDATE
              SET last_user_id=EXCLUDED.last_user_id, updated_at=NOW()
        """, (group_key, duty_id, user_id))
        db_connection.get_connection().commit()

def get_member_rank_effective(group_key: str, user_id: int, on_date) -> Optional[int]:
    """
    Возвращает ранг 1..3 с учётом ротации (flip 1↔2 по правилу группы).
    Если правил нет — базовый ранг.
    """
    base = get_member_rank(group_key, user_id)
    if base not in (1, 2, 3):
        return base
    try:
        from .rank_rotation_repository import get_rule
        rule = get_rule(group_key)
    except Exception:
        rule = None
    if not rule or not rule.get("is_enabled"):
        return base
    try:
        period = int(rule["period_days"])
        epoch = rule["epoch"]
        if period <= 0 or not epoch:
            return base
        if on_date is None:
            with db_connection.get_connection().cursor() as cur:
                cur.execute("SELECT CURRENT_DATE")
                on_date = cur.fetchone()[0]
        steps = (on_date - epoch).days // period
        if (rule.get("mode") or "flip_1_2").lower() == "flip_1_2":
            if steps % 2 == 1:
                if base == 1: return 2
                if base == 2: return 1
        return base
    except Exception:
        return base

