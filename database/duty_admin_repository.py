# /home/telegrambot/shift_tracker_bot/database/duty_admin_repository.py
# -*- coding: utf-8 -*-
"""
Репозиторий для работы с дополнительными данными дежурств:
- Ранги участников (веса для алгоритма распределения)
- Исключения из дежурств (временные периоды когда пользователь не доступен)
- Round-robin курсоры (последние назначения для циклического распределения)
"""

from typing import Optional, Dict, Any, List
from datetime import date
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

# ---- EXCLUSIONS ----
def add_exclusion(user_id: int, date_from: date, date_to: date, group_key: Optional[str], reason: Optional[str], admin_id: Optional[int]) -> int:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            INSERT INTO duty_exclusions (user_id, group_key, date_from, date_to, reason, created_by)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (user_id, group_key, date_from, date_to, reason, admin_id))
        new_id = cur.fetchone()[0]
        db_connection.get_connection().commit()
        return new_id

def remove_exclusion(excl_id: int) -> bool:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("DELETE FROM duty_exclusions WHERE id=%s", (excl_id,))
        db_connection.get_connection().commit()
        return cur.rowcount > 0

def list_exclusions(on_date: Optional[date] = None, group_key: Optional[str] = None, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    where, params = ["1=1"], []
    if on_date is not None:
        where.append("date_from <= %s AND date_to >= %s"); params += [on_date, on_date]
    if group_key is not None:
        where.append("(group_key IS NULL OR group_key = %s)"); params.append(group_key)
    if user_id is not None:
        where.append("user_id = %s"); params.append(user_id)
    sql = f"""
        SELECT id, user_id, group_key, date_from, date_to, reason, created_by, created_at
        FROM duty_exclusions
        WHERE {' AND '.join(where)}
        ORDER BY date_from DESC, id DESC
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [{"id": r[0], "user_id": r[1], "group_key": r[2], "date_from": r[3], "date_to": r[4], "reason": r[5], "created_by": r[6], "created_at": r[7]} for r in rows]

def is_user_excluded_on(group_key: str, user_id: int, on_date: date) -> bool:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            SELECT 1 FROM duty_exclusions
            WHERE user_id=%s
              AND (group_key IS NULL OR group_key=%s)
              AND date_from <= %s AND date_to >= %s
            LIMIT 1
        """, (user_id, group_key, on_date, on_date))
        return cur.fetchone() is not None

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

def reset_assignments_for_date(on_date: date, group_key: Optional[str] = None) -> int:
    """
    Удаляет назначения из duty_assignments за указанную дату.
    Если задан group_key — удаляет только по этой группе.
    Возвращает количество удалённых строк.
    """
    sql = "DELETE FROM duty_assignments WHERE on_date=%s"
    params = [on_date]
    if group_key:
        sql += " AND group_key=%s"
        params.append(group_key)

    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(sql, params)
            deleted = cur.rowcount or 0
            db_connection.get_connection().commit()
            return deleted
    except Exception:
        db_connection.get_connection().rollback()
        logger.exception("reset_assignments_for_date failed")
        return 0

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

