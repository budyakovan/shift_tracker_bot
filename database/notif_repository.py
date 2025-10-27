# /home/telegrambot/shift_tracker_bot/database/notif_repository.py
# -*- coding: utf-8 -*-
"""
Хранилище соответствий тайм-группа → (chat_id, topic_id) для разных видов оповещений.

Таблица: notif_endpoints
- group_key TEXT          — ключ тайм-группы (например, "vrn3")
- kind TEXT DEFAULT 'general' — тип оповещения (например, 'afk', 'duty', 'alerts', 'general')
- chat_id BIGINT          — целевой чат
- topic_id BIGINT NULL    — целевой топик (если это форум-топик), иначе NULL
- created_at timestamptz
- updated_at timestamptz
UNIQUE (group_key, kind)

Основные функции:
- set_target(group_key, chat_id, topic_id=None, kind='general')
- get_target(group_key, kind='general')
- list_targets(kind=None)
- clear_target(group_key, kind='general')
- resolve_target(group_key, kind='afk', fallback_to_general=True)

ПРИМЕЧАНИЕ ПО МИГРАЦИИ:
Создать таблицу (один раз):

CREATE TABLE IF NOT EXISTS notif_endpoints (
    id BIGSERIAL PRIMARY KEY,
    group_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'general',
    chat_id BIGINT NOT NULL,
    topic_id BIGINT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (group_key, kind)
);

CREATE INDEX IF NOT EXISTS idx_notif_endpoints_group_kind
    ON notif_endpoints (group_key, kind);
"""

from typing import Optional, List, Dict, Any
import logging
from .connection import db_connection

logger = logging.getLogger(__name__)

def resolve_listen_group(chat_id: int, topic_id: Optional[int]) -> Optional[str]:
    """
    Вернёт group_key, если чат/топик помечен kind='listen', иначе None.
    """
    rec = find_group_by_channel(chat_id, topic_id, kind="listen")
    return rec["group_key"] if rec else None


def set_target(group_key: str,
               chat_id: int,
               topic_id: Optional[int] = None,
               kind: str = "general") -> Dict[str, Any]:
    """
    Установить/обновить конечную точку для уведомлений данной группы и типа.
    """
    assert group_key, "group_key is required"
    assert chat_id, "chat_id is required"

    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            INSERT INTO notif_endpoints (group_key, kind, chat_id, topic_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (group_key, kind) DO UPDATE
               SET chat_id = EXCLUDED.chat_id,
                   topic_id = EXCLUDED.topic_id,
                   updated_at = NOW()
            RETURNING group_key, kind, chat_id, topic_id
        """, (group_key, kind, int(chat_id), int(topic_id) if topic_id is not None else None))
        row = cur.fetchone()
        db_connection.get_connection().commit()

    return {
        "group_key": row[0],
        "kind": row[1],
        "chat_id": int(row[2]),
        "topic_id": int(row[3]) if row[3] is not None else None,
    }


def get_target(group_key: str, kind: str = "general") -> Optional[Dict[str, Any]]:
    """
    Получить точку для конкретной группы и типа.
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            SELECT group_key, kind, chat_id, topic_id
              FROM notif_endpoints
             WHERE group_key = %s AND kind = %s
            LIMIT 1
        """, (group_key, kind))
        row = cur.fetchone()

    if not row:
        return None
    return {
        "group_key": row[0],
        "kind": row[1],
        "chat_id": int(row[2]),
        "topic_id": int(row[3]) if row[3] is not None else None,
    }


def list_targets(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Список всех точек. Если указан kind — фильтруем по нему.
    """
    if kind:
        sql = "SELECT group_key, kind, chat_id, topic_id FROM notif_endpoints WHERE kind=%s ORDER BY group_key"
        params = (kind,)
    else:
        sql = "SELECT group_key, kind, chat_id, topic_id FROM notif_endpoints ORDER BY group_key, kind"
        params = ()

    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() or []

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "group_key": r[0],
            "kind": r[1],
            "chat_id": int(r[2]),
            "topic_id": int(r[3]) if r[3] is not None else None,
        })
    return out


def clear_target(group_key: str, kind: str = "general") -> bool:
    """
    Удалить точку группы/типа. Возвращает True, если что-то удалили.
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute("DELETE FROM notif_endpoints WHERE group_key=%s AND kind=%s", (group_key, kind))
        deleted = cur.rowcount > 0
        db_connection.get_connection().commit()
    return deleted


def resolve_target(group_key: Optional[str],
                   kind: str = "general",
                   fallback_to_general: bool = True) -> Optional[Dict[str, Any]]:
    """
    Разрешить конечную точку:
      1) (group_key, kind)
      2) если fallback_to_general=True, то (group_key, 'general')
      3) иначе None
    """
    if not group_key:
        return None

    one = get_target(group_key, kind=kind)
    if one:
        return one
    if fallback_to_general and kind != "general":
        return get_target(group_key, kind="general")
    return None

# database/notif_repository.py

def find_group_by_channel(chat_id: int, topic_id: Optional[int], kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Ищем endpoint по (chat_id, topic_id). Опционально фильтруем по kind.
    Сначала точное совпадение topic_id (NULL==NULL), потом фолбэк на весь чат (topic_id IS NULL).
    """
    with db_connection.get_connection().cursor() as cur:
        if kind is None:
            cur.execute(
                """
                SELECT group_key, chat_id, topic_id, kind
                FROM notif_endpoints
                WHERE chat_id = %s
                  AND ((topic_id IS NULL AND %s IS NULL) OR topic_id = %s)
                ORDER BY (topic_id IS NOT NULL) DESC
                LIMIT 1
                """,
                (chat_id, topic_id, topic_id),
            )
        else:
            cur.execute(
                """
                SELECT group_key, chat_id, topic_id, kind
                FROM notif_endpoints
                WHERE chat_id = %s
                  AND kind = %s
                  AND ((topic_id IS NULL AND %s IS NULL) OR topic_id = %s)
                ORDER BY (topic_id IS NOT NULL) DESC
                LIMIT 1
                """,
                (chat_id, kind, topic_id, topic_id),
            )
        row = cur.fetchone()
        if row:
            return {"group_key": row[0], "chat_id": row[1], "topic_id": row[2], "kind": row[3]}

        # фолбэк: endpoint на весь чат
        if kind is None:
            cur.execute(
                """
                SELECT group_key, chat_id, topic_id, kind
                FROM notif_endpoints
                WHERE chat_id = %s
                  AND topic_id IS NULL
                LIMIT 1
                """,
                (chat_id,),
            )
        else:
            cur.execute(
                """
                SELECT group_key, chat_id, topic_id, kind
                FROM notif_endpoints
                WHERE chat_id = %s
                  AND topic_id IS NULL
                  AND kind = %s
                LIMIT 1
                """,
                (chat_id, kind),
            )
        row = cur.fetchone()
        if row:
            return {"group_key": row[0], "chat_id": row[1], "topic_id": row[2], "kind": row[3]}
    return None
