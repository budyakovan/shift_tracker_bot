# /home/telegrambot/shift_tracker_bot/database/absence_repository.py
# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any
from datetime import date
import logging

from .connection import db_connection   # только соединение

logger = logging.getLogger(__name__)

def _row_to_dict(row) -> Dict[str, Any]:
    return {
        "id": row[0], "user_id": row[1], "absence_type": row[2],
        "date_from": row[3], "date_to": row[4], "comment": row[5],
        "created_by": row[6], "updated_by": row[7],
        "created_at": row[8], "updated_at": row[9], "is_deleted": row[10],
    }

def create_absence(user_id: int, absence_type: str, date_from: date, date_to: date,
                   comment: Optional[str], author_id: int) -> Optional[int]:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("""
                INSERT INTO user_absences (user_id, absence_type, date_from, date_to, comment, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, absence_type, date_from, date_to, comment, author_id))
            new_id = cur.fetchone()[0]
            db_connection.get_connection().commit()
            return new_id
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.error(f"create_absence error: {e}")
        return None

def update_absence(absence_id: int, user_id: int, date_from: Optional[date] = None,
                   date_to: Optional[date] = None, comment: Optional[str] = None,
                   editor_id: Optional[int] = None, is_admin: bool = False) -> bool:
    try:
        with db_connection.get_connection().cursor() as cur:
            # Проверка прав
            if not is_admin:
                cur.execute("SELECT 1 FROM user_absences WHERE id=%s AND user_id=%s AND is_deleted=FALSE",
                            (absence_id, user_id))
            else:
                cur.execute("SELECT 1 FROM user_absences WHERE id=%s AND is_deleted=FALSE", (absence_id,))
            if cur.fetchone() is None:
                return False

            fields, params = [], []
            if date_from is not None: fields.append("date_from=%s"); params.append(date_from)
            if date_to   is not None: fields.append("date_to=%s");   params.append(date_to)
            if comment   is not None: fields.append("comment=%s");   params.append(comment)
            fields.append("updated_at=NOW()")
            if editor_id is not None: fields.append("updated_by=%s"); params.append(editor_id)

            if not fields: return True
            params.append(absence_id)
            cur.execute(f"UPDATE user_absences SET {', '.join(fields)} WHERE id=%s AND is_deleted=FALSE", params)
            db_connection.get_connection().commit()
            return cur.rowcount > 0
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.error(f"update_absence error: {e}")
        return False

def soft_delete_absence(absence_id: int, user_id: int, is_admin: bool = False) -> bool:
    try:
        with db_connection.get_connection().cursor() as cur:
            if not is_admin:
                cur.execute("""
                    UPDATE user_absences SET is_deleted=TRUE, updated_at=NOW()
                    WHERE id=%s AND user_id=%s AND is_deleted=FALSE
                """, (absence_id, user_id))
            else:
                cur.execute("""
                    UPDATE user_absences SET is_deleted=TRUE, updated_at=NOW()
                    WHERE id=%s AND is_deleted=FALSE
                """, (absence_id,))
            db_connection.get_connection().commit()
            return cur.rowcount > 0
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.error(f"soft_delete_absence error: {e}")
        return False

def list_absences(user_id: Optional[int] = None, absence_type: Optional[str] = None,
                  only_active: bool = True, from_date: Optional[date] = None,
                  to_date: Optional[date] = None) -> List[Dict[str, Any]]:
    where, params = ["1=1"], []
    if user_id is not None:      where.append("user_id=%s");      params.append(user_id)
    if absence_type is not None: where.append("absence_type=%s"); params.append(absence_type)
    if only_active:              where.append("is_deleted=FALSE")
    if from_date is not None:    where.append("date_to >= %s");   params.append(from_date)
    if to_date is not None:      where.append("date_from <= %s"); params.append(to_date)
    sql = f"""
        SELECT id, user_id, absence_type, date_from, date_to, comment, created_by, updated_by, created_at, updated_at, is_deleted
        FROM user_absences
        WHERE {' AND '.join(where)}
        ORDER BY date_from DESC, id DESC
        LIMIT 200
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

# === Новые агрегированные выборки с данными пользователя ===
def list_absences_with_users(absence_type: Optional[str] = None,
                             from_date: Optional[date] = None,
                             to_date: Optional[date] = None,
                             only_active: bool = True) -> List[Dict[str, Any]]:
    """
    Возвращает записи об отсутствиях с ФИО/username пользователя.
    Требуется таблица users(user_id, first_name, last_name, username, ...).
    """
    where, params = ["ua.is_deleted=FALSE" if only_active else "1=1"], []
    if absence_type is not None:
        where.append("ua.absence_type=%s"); params.append(absence_type)
    if from_date is not None:
        where.append("ua.date_to >= %s");   params.append(from_date)
    if to_date is not None:
        where.append("ua.date_from <= %s"); params.append(to_date)

    sql = f"""
        SELECT
            ua.id, ua.user_id, ua.absence_type, ua.date_from, ua.date_to, ua.comment,
            u.first_name, u.last_name, u.username
        FROM user_absences ua
        JOIN users u ON u.user_id = ua.user_id
        WHERE {' AND '.join(where)}
        ORDER BY ua.date_from DESC, ua.id DESC
        LIMIT 300
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "user_id": r[1], "absence_type": r[2],
                "date_from": r[3], "date_to": r[4], "comment": r[5],
                "first_name": r[6], "last_name": r[7], "username": r[8],
            })
        return out

def get_absence_on_date(user_id: int, target_date) -> Optional[Dict[str, Any]]:
    """
    Возвращает одну запись об отсутствии, если target_date попадает в интервал.
    Иначе None.
    """
    sql = """
        SELECT id, user_id, absence_type, date_from, date_to, comment, created_by, updated_by, created_at, updated_at, is_deleted
        FROM user_absences
        WHERE user_id = %s
          AND is_deleted = FALSE
          AND date_from <= %s
          AND date_to   >= %s
        ORDER BY date_from DESC, id DESC
        LIMIT 1
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, (user_id, target_date, target_date))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

# --- compatibility alias for old handlers imports ---
def list_absences_period(*args, **kwargs):
    # просто прокидываем параметры в уже существующую функцию
    return list_absences(*args, **kwargs)
