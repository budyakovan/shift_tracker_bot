# /home/telegrambot/shift_tracker_bot/database/pair_repository.py
# -*- coding: utf-8 -*-
from typing import List, Dict, Tuple
from datetime import date
from .connection import db_connection
import logging

logger = logging.getLogger(__name__)
LOG_TABLE = "pair_work_log"  # (group_key, on_date, user_a, user_b)

def _norm_pair(u1: int, u2: int) -> Tuple[int, int]:
    a, b = int(u1), int(u2)
    return (a, b) if a <= b else (b, a)

def log_pair_day(group_key: str, on_date: date, user1: int, user2: int) -> bool:
    """Логируем факт совместной смены в офисе (двое, будний день)."""
    a, b = _norm_pair(user1, user2)
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(f"""
                INSERT INTO {LOG_TABLE} (group_key, on_date, user_a, user_b)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (group_key, on_date) DO UPDATE
                  SET user_a=EXCLUDED.user_a, user_b=EXCLUDED.user_b
            """, (group_key, on_date, a, b))
        db_connection.get_connection().commit()
        return True
    except Exception:
        db_connection.get_connection().rollback()
        logger.exception("pair.log failed g=%s d=%s a=%s b=%s", group_key, on_date, a, b)
        return False

def pair_stats(group_key: str, date_from: date, date_to: date) -> List[Dict]:
    """Сколько дней отработала вместе каждая пара."""
    sql = f"""
        SELECT user_a, user_b, COUNT(*) AS days
        FROM {LOG_TABLE}
        WHERE group_key=%s AND on_date BETWEEN %s AND %s
        GROUP BY user_a, user_b
        ORDER BY days DESC, user_a, user_b
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, (group_key, date_from, date_to))
        rows = cur.fetchall() or []
    return [{"user_a": r[0], "user_b": r[1], "days": int(r[2])} for r in rows]

def get_pair_day(group_key: str, on_date: date) -> Tuple[int, int] | None:
    """Возвращает пару (user_a, user_b) из журнала для даты, если записана."""
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(f"""
                SELECT user_a, user_b
                  FROM {LOG_TABLE}
                 WHERE group_key=%s AND on_date=%s
                 LIMIT 1
            """, (group_key, on_date))
            row = cur.fetchone()
            if not row:
                return None
            a, b = int(row[0]), int(row[1])
            if a and b and a != b:
                return (a, b) if a <= b else (b, a)
    except Exception:
        logger.exception("pair.get_pair_day failed g=%s d=%s", group_key, on_date)
    return None
