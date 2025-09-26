# -*- coding: utf-8 -*-
"""
group_repository.py — репозиторий для работы с time-группами (группы расписаний)
и совместимыми схемами членства.

Используется:
- /admin_time_groups_list (чтение time_groups)
- /admin_group_rename <key> <new_name...> (обновление name в time_groups)
- list_users_in_group(group_key) — универсально ищет участников по нескольким схемам.
- get_user_group(user_id) — возвращает группу пользователя (key, name)

Ожидаемая схема time_groups (ориентир, адаптируйте при необходимости):
----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS time_groups (
    id               SERIAL PRIMARY KEY,
    key              TEXT UNIQUE NOT NULL,      -- 'vrn1', 'vdk1', 'group_archakov' ...
    profile_key      TEXT NOT NULL,             -- 'team_vologzhin' и т.п.
    epoch            DATE,
    period           INTEGER NOT NULL DEFAULT 8,-- 8-дневка по умолчанию
    tz               TEXT,                      -- IANA, напр. 'Europe/Moscow'
    tz_offset_hours  INTEGER NOT NULL DEFAULT 0,
    name             TEXT                       -- человекочитаемое имя (может быть NULL)
);
----------------------------------------------------------------
"""

from __future__ import annotations

import logging
from typing import List, Dict, Optional, Any

from database.connection import db_connection

logger = logging.getLogger(__name__)

TABLE = "time_groups"  # если у вас иное имя — измените здесь


# ===========================
# ВНУТРЕННИЕ ХЕЛПЕРЫ (PG)
# ===========================

def _conn():
    """
    Возвращает живое соединение psycopg2 от нашего синглтона.
    Соединение не закрываем здесь — им управляет DatabaseConnection.
    """
    return db_connection.get_connection()


def _ensure_name_column() -> None:
    """
    Гарантируем наличие колонки name в time_groups (PostgreSQL).
    Безопасно вызывать многократно.
    """
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS name TEXT")
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("Не удалось обеспечить наличие колонки name в %s: %s", TABLE, e)


def _table_exists(cur, table_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        LIMIT 1
        """,
        (table_name,),
    )
    return cur.fetchone() is not None


# ===========================
# ОСНОВНЫЕ ОПЕРАЦИИ С ГРУППАМИ
# ===========================

def list_groups() -> List[Dict[str, Any]]:
    """
    Возвращает список time-групп для админского вывода.
    """
    sql = f"""
        SELECT key, profile_key, epoch, period, tz, tz_offset_hours, name
        FROM {TABLE}
        ORDER BY key
    """
    conn = _conn()
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "key": r[0],
                "profile_key": r[1],
                "epoch": r[2],
                "period": r[3],
                "tz": r[4],
                "tz_offset_hours": r[5],
                "name": r[6],
            }
        )
    return out


def get_by_key(key: str) -> Optional[Dict[str, Any]]:
    """
    Возвращает одну группу time_groups по ключу или None.
    """
    sql = f"""
        SELECT key, profile_key, epoch, period, tz, tz_offset_hours, name
        FROM {TABLE}
        WHERE key = %s
        LIMIT 1
    """
    conn = _conn()
    cur = conn.cursor()
    cur.execute(sql, (key,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {
        "key": row[0],
        "profile_key": row[1],
        "epoch": row[2],
        "period": row[3],
        "tz": row[4],
        "tz_offset_hours": row[5],
        "name": row[6],
    }


def update_name(key: str, new_name: str) -> bool:
    """
    Обновляет человекочитаемое имя группы (колонка name) в time_groups.
    Возвращает True, если строка обновлена (rowcount > 0).
    """
    if not key or not new_name:
        return False

    _ensure_name_column()

    sql = f"UPDATE {TABLE} SET name = %s WHERE key = %s"
    conn = _conn()
    cur = conn.cursor()
    cur.execute(sql, (new_name.strip(), key.strip()))
    conn.commit()
    updated = cur.rowcount > 0
    cur.close()
    return updated


# ===========================
# ПОЛЬЗОВАТЕЛИ ГРУППЫ (универсально)
# ===========================

def list_users_in_group(group_key: str) -> List[Dict[str, Any]]:
    """
    Возвращает участников группы как список словарей:
      { "user_id": int, "username": str|None, "first_name": str|None, "last_name": str|None }

    Поддерживаются разные варианты схемы членства — проверяются по очереди:
      1) time_group_members(user_id, group_key) + users(...)
      2) duty_group_members(user_id, group_id) + duty_groups(id,key,...)  [если у вас такая историческая схема]
      3) group_users(user_id, group_key) + users(...)

    Функция возвращает [] если ничего не найдено.
    """
    conn = _conn()
    cur = conn.cursor()

    # (1) time_group_members (актуально для time_groups)
    try:
        if _table_exists(cur, "time_group_members"):
            cur.execute(
                """
                SELECT u.user_id, u.username, u.first_name, u.last_name
                FROM time_group_members tgm
                LEFT JOIN users u ON u.user_id = tgm.user_id
                WHERE tgm.group_key = %s
                ORDER BY COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''),
                         COALESCE(u.username,''), u.user_id::text
                """,
                (group_key,),
            )
            rows = cur.fetchall()
            if rows:
                cur.close()
                return [
                    {
                        "user_id": r[0],
                        "username": r[1],
                        "first_name": r[2],
                        "last_name": r[3],
                    }
                    for r in rows
                ]
    except Exception:
        pass

    # (2) duty_group_members + duty_groups (исторически/альтернативно)
    try:
        if _table_exists(cur, "duty_group_members") and _table_exists(cur, "duty_groups"):
            cur.execute(
                """
                SELECT u.user_id, u.username, u.first_name, u.last_name
                FROM duty_group_members gm
                JOIN duty_groups dg ON dg.id = gm.group_id
                LEFT JOIN users u ON u.user_id = gm.user_id
                WHERE dg.key = %s
                ORDER BY COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''),
                         COALESCE(u.username,''), u.user_id::text
                """,
                (group_key,),
            )
            rows = cur.fetchall()
            if rows:
                cur.close()
                return [
                    {
                        "user_id": r[0],
                        "username": r[1],
                        "first_name": r[2],
                        "last_name": r[3],
                    }
                    for r in rows
                ]
    except Exception:
        pass

    # (3) group_users (старое имя таблицы связей)
    try:
        if _table_exists(cur, "group_users"):
            cur.execute(
                """
                SELECT u.user_id, u.username, u.first_name, u.last_name
                FROM group_users gu
                LEFT JOIN users u ON u.user_id = gu.user_id
                WHERE gu.group_key = %s
                ORDER BY COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''),
                         COALESCE(u.username,''), u.user_id::text
                """,
                (group_key,),
            )
            rows = cur.fetchall()
            if rows:
                cur.close()
                return [
                    {
                        "user_id": r[0],
                        "username": r[1],
                        "first_name": r[2],
                        "last_name": r[3],
                    }
                    for r in rows
                ]
    except Exception:
        pass

    cur.close()
    return []


def  get_user_group(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Возвращает словарь с группой пользователя:
      { "key": "<group_key>", "name": "<group_name or key>" }
    или None, если не нашли.

    Проверяются варианты схемы:
      1) time_group_members(user_id, group_key) + time_groups(key,name)
      2) duty_group_members(user_id, group_id) + duty_groups(id,key,name)
      3) group_users(user_id, group_key) + time_groups(key,name)
    """
    conn = _conn()
    cur = conn.cursor()

    # (1) time_group_members → time_groups
    try:
        if _table_exists(cur, "time_group_members"):
            cur.execute(
                f"""
                SELECT tg.key, COALESCE(NULLIF(tg.name, ''), tg.key) AS name
                FROM time_group_members tgm
                JOIN {TABLE} tg ON tg.key = tgm.group_key
                WHERE tgm.user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return {"key": row[0], "name": row[1]}
    except Exception:
        pass

    # (2) duty_group_members → duty_groups (исторический вариант)
    try:
        if _table_exists(cur, "duty_group_members") and _table_exists(cur, "duty_groups"):
            cur.execute(
                """
                SELECT dg.key, COALESCE(NULLIF(dg.name, ''), dg.key) AS name
                FROM duty_group_members gm
                JOIN duty_groups dg ON dg.id = gm.group_id
                WHERE gm.user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return {"key": row[0], "name": row[1]}
    except Exception:
        pass

    # (3) group_users → time_groups
    try:
        if _table_exists(cur, "group_users"):
            cur.execute(
                f"""
                SELECT tg.key, COALESCE(NULLIF(tg.name, ''), tg.key) AS name
                FROM group_users gu
                JOIN {TABLE} tg ON tg.key = gu.group_key
                WHERE gu.user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return {"key": row[0], "name": row[1]}
    except Exception:
        pass

    cur.close()
    return None

def add_user_to_time_group(group_key: str, user_id: int, base_pos: int) -> bool:
    """
    Добавляет/обновляет участника группы в time_group_members.
    Требует таблицу:
      CREATE TABLE IF NOT EXISTS time_group_members (
        user_id BIGINT NOT NULL,
        group_key TEXT NOT NULL,
        base_pos INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, group_key)
      );
    """
    conn = _conn()
    with conn.cursor() as cur:
        # убеждаемся, что группа существует
        cur.execute(f"SELECT 1 FROM {TABLE} WHERE key=%s LIMIT 1", (group_key,))
        if cur.fetchone() is None:
            return False
        # апсертом пишем участника
        cur.execute("""
            INSERT INTO time_group_members (user_id, group_key, base_pos)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, group_key) DO UPDATE SET base_pos=EXCLUDED.base_pos
        """, (int(user_id), group_key, int(base_pos)))
        conn.commit()
        return True

def remove_user_from_time_group(group_key: str, user_id: int) -> bool:
    conn = _conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM time_group_members WHERE user_id=%s AND group_key=%s", (int(user_id), group_key))
        conn.commit()
        return cur.rowcount > 0

