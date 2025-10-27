# /home/telegrambot/shift_tracker_bot/database/users_repository.py
# -*- coding: utf-8 -*-
"""
Функции работы с пользователями (без классов).
Совместимы с прежними именами: approve_user/remove_user/promote_user/demote_user/set_admin/...
"""

import json
import logging
from typing import List, Optional, Dict, Any
from .connection import db_connection

logger = logging.getLogger(__name__)

# Обратная совместимость по ролям
USER_ROLE_USER = "user"
USER_ROLE_ADMIN = "admin"

# ---------- Внутреннее ----------
def _get_role_id(role_name: str) -> Optional[int]:
    try:
        with db_connection.get_connection().cursor() as cursor:
            cursor.execute(
                "SELECT id FROM user_roles WHERE LOWER(name) = LOWER(%s) LIMIT 1",
                (role_name,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error("Error getting role id: %s", e)
        return None

# ---------- Роли / статусы ----------
def set_role(user_id: int, role_name: str, admin_id: Optional[int] = None) -> bool:
    role_id = _get_role_id(role_name)
    if role_id is None:
        logger.error("Role '%s' not found", role_name)
        return False

    conn = db_connection.get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_settings
                    SET role_id = %s, updated_at = NOW()
                    WHERE user_id = %s
                    """,
                    (role_id, user_id),
                )
                if cur.rowcount == 0:
                    logger.warning("set_role: user_settings row not found for user_id=%s", user_id)
                    return False

                if admin_id is not None:
                    cur.execute(
                        """
                        INSERT INTO admin_actions (admin_id, action_type, target_user_id, details)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (admin_id, "set_role", user_id, json.dumps({"role": role_name})),
                    )
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("Error setting role: %s", e)
        return False

# Алиасы совместимости
def update_role(user_id: int, role_name: str, admin_id: Optional[int] = None) -> bool:
    return set_role(user_id, role_name, admin_id)

def change_role(user_id: int, role_name: str, admin_id: Optional[int] = None) -> bool:
    return set_role(user_id, role_name, admin_id)

def promote_user(user_id: int, admin_id: Optional[int] = None) -> bool:
    return set_role(user_id, USER_ROLE_ADMIN, admin_id)

def demote_user(user_id: int, admin_id: Optional[int] = None) -> bool:
    return set_role(user_id, USER_ROLE_USER, admin_id)

def set_admin(user_id: int, is_admin: bool, admin_id: Optional[int] = None) -> bool:
    return set_role(user_id, USER_ROLE_ADMIN if is_admin else USER_ROLE_USER, admin_id)

def set_is_admin(user_id: int, is_admin: bool, admin_id: Optional[int] = None) -> bool:
    return set_admin(user_id, is_admin, admin_id)

# ---------- Пользователи ----------
def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    try:
        with db_connection.get_connection().cursor() as cursor:
            cursor.execute(
                """
                SELECT us.user_id, ur.name as role_name, us.is_approved
                FROM user_settings us
                LEFT JOIN user_roles ur ON us.role_id = ur.id
                WHERE us.user_id = %s
                """,
                (user_id,),
            )
            result = cursor.fetchone()
            if result:
                return {
                    "user_id": result[0],
                    "role": result[1] if result[1] else USER_ROLE_USER,
                    "is_approved": result[2] if result[2] else False,
                }
            return None
    except Exception as e:
        logger.error("Error getting user: %s", e)
        return None

def create_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> bool:
    try:
        with db_connection.get_connection().cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    updated_at = NOW()
                """,
                (user_id, username, first_name, last_name),
            )
            cursor.execute("SELECT id FROM user_roles WHERE name = %s", (USER_ROLE_USER,))
            role_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO user_settings (user_id, role_id, epoch_date, is_approved)
                VALUES (%s, %s, NOW(), %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, role_id, False),
            )
            db_connection.get_connection().commit()
            return True
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.error("Error creating user: %s", e)
        return False

def remove_user(user_id: int) -> bool:
    conn = db_connection.get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE admin_actions SET admin_id = NULL WHERE admin_id = %s;", (user_id,))
                cur.execute("DELETE FROM admin_actions WHERE target_user_id = %s;", (user_id,))
                cur.execute("DELETE FROM user_settings WHERE user_id = %s;", (user_id,))
                cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
        return True
    except Exception as e:
        logger.error("Error removing user: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False

def approve_user(user_id: int, admin_id: int) -> bool:
    try:
        with db_connection.get_connection().cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_settings
                SET is_approved = TRUE, updated_at = NOW()
                WHERE user_id = %s
                """,
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO admin_actions (admin_id, action_type, target_user_id, details)
                VALUES (%s, %s, %s, %s)
                """,
                (admin_id, "user_approval", user_id, '{"action": "approve"}'),
            )
            db_connection.get_connection().commit()
            return True
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.error("Error approving user: %s", e)
        return False

def get_pending_users() -> List[Dict[str, Any]]:
    try:
        with db_connection.get_connection().cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    us.user_id,
                    us.created_at,
                    u.username,
                    u.first_name,
                    u.last_name
                FROM user_settings us
                LEFT JOIN users u ON us.user_id = u.user_id
                WHERE us.is_approved = FALSE
                ORDER BY us.created_at DESC
                """
            )
            return [
                {
                    "user_id": row[0],
                    "created_at": row[1],
                    "username": row[2],
                    "first_name": row[3],
                    "last_name": row[4],
                }
                for row in cursor.fetchall()
            ]
    except Exception as e:
        logger.error("Error getting pending users: %s", e)
        return []

def get_all_users() -> List[Dict[str, Any]]:
    try:
        with db_connection.get_connection().cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    us.user_id,
                    ur.name as role_name,
                    us.is_approved,
                    us.created_at,
                    us.updated_at,
                    u.username,
                    u.first_name,
                    u.last_name
                FROM user_settings us
                LEFT JOIN user_roles ur ON us.role_id = ur.id
                LEFT JOIN users u ON us.user_id = u.user_id
                ORDER BY us.created_at DESC
                """
            )
            return [
                {
                    "user_id": row[0],
                    "role": row[1] if row[1] else USER_ROLE_USER,
                    "is_approved": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                    "username": row[5],
                    "first_name": row[6],
                    "last_name": row[7],
                }
                for row in cursor.fetchall()
            ]
    except Exception as e:
        logger.error("Error getting all users: %s", e)
        return []

def is_user_admin(user_id: int) -> bool:
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ur.name
            FROM user_settings us
            JOIN user_roles ur ON ur.id = us.role_id
            WHERE us.user_id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        return str(row[0]).strip().lower() == "admin"

# ---------- Нормализация users ----------
def update_all_users() -> int:
    try:
        conn = db_connection.get_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH prepared AS (
                        SELECT
                            u.user_id,
                            NULLIF(REGEXP_REPLACE(COALESCE(u.username, ''), '^\s*@', ''), '') AS new_username,
                            NULLIF(BTRIM(COALESCE(u.first_name, '')), '')                        AS new_first_name,
                            NULLIF(BTRIM(COALESCE(u.last_name,  '')), '')                        AS new_last_name
                        FROM users u
                    ),
                    diffs AS (
                        SELECT u.user_id, p.new_username, p.new_first_name, p.new_last_name
                        FROM users u
                        JOIN prepared p USING(user_id)
                        WHERE (u.username   IS DISTINCT FROM p.new_username)
                           OR (u.first_name IS DISTINCT FROM p.new_first_name)
                           OR (u.last_name  IS DISTINCT FROM p.new_last_name)
                    )
                    UPDATE users u
                    SET username   = d.new_username,
                        first_name = d.new_first_name,
                        last_name  = d.new_last_name,
                        updated_at = NOW()
                    FROM diffs d
                    WHERE u.user_id = d.user_id
                    RETURNING u.user_id
                    """
                )
                changed = cur.rowcount or 0
        return changed
    except Exception as e:
        logger.error("Error updating all users: %s", e)
        return 0


