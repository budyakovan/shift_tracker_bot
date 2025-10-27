# /home/telegrambot/shift_tracker_bot/database/group_time_link_repository.py
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Назначение файла
# -----------------------------------------------------------------------------
# Этот модуль инкапсулирует операции над связкой "группа ↔ time-группа"
# через таблицу group_time_link. Предоставляет простой репозиторий с CRUD-
# методами:
#   - set_link(group_key, time_group_key)     — создать/обновить связь
#   - remove_link(group_key)                  — удалить связь по ключу группы
#   - get_link(group_key)                     — получить time_group_key по group_key
#   - find_by_time_group(time_group_key)      — найти запись по time_group_key
#
# Особенности реализации:
#   • Используется контекстный менеджер _cursor(), который:
#       - берёт соединение у db_connection (get_connection/connect/connection),
#       - открывает курсор и отдаёт пару (conn, cur),
#       - по выходу пытается сделать commit (или rollback при исключении),
#       - закрывает курсор и САМО СОЕДИНЕНИЕ.
#     ВАЖНО: закрытие соединения здесь означает, что при следующем вызове
#     db_connection создаст новое. Если вы хотите держать соединение
#     открытым дольше, не используйте этот менеджер или измените его логику.
#   • ON CONFLICT (group_key) для upsert-сценария при установке связи.
#   • Все запросы параметризованы (без конкатенации SQL), безопасны к SQL-инъекциям.
# -----------------------------------------------------------------------------

import logging
from contextlib import contextmanager
from typing import Optional, Dict

from database.connection import db_connection

logger = logging.getLogger(__name__)

@contextmanager
def _cursor():
    """
    Универсальный менеджер контекста для работы с БД:
    - Получает соединение из db_connection (поддержка нескольких API-имен).
    - Открывает курсор и возвращает (conn, cur).
    - Делает commit по успешному выходу, rollback при исключении.
    - Закрывает курсор и соединение в любом случае.

    Примечание: здесь закрывается и курсор, и conn — это осознанное решение,
    но оно может идти вразрез с паттерном "единого долгоживущего соединения".
    """
    # выбираем доступный способ получить соединение из синглтона
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
        yield conn, cur  # отдаём наружу пару (соединение, курсор)
        try:
            conn.commit()  # пытаемся коммитнуть изменения
        except Exception:
            pass
    except Exception:
        # при ошибке пытаемся откатить транзакцию
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        # аккуратно закрываем курсор и соединение
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

def set_link(group_key: str, time_group_key: str) -> None:
    """
    Создаёт или обновляет связь между group_key и time_group_key.
    Если запись с таким group_key уже есть — обновляет time_group_key и linked_at.
    """
    sql = """
        INSERT INTO group_time_link (group_key, time_group_key)
        VALUES (%s, %s)
        ON CONFLICT (group_key)
        DO UPDATE SET time_group_key=EXCLUDED.time_group_key, linked_at=NOW()
    """
    with _cursor() as (conn, cur):
        cur.execute(sql, (group_key, time_group_key))

def remove_link(group_key: str) -> bool:
    """
    Удаляет связь по ключу группы.
    Возвращает True, если была удалена хотя бы одна строка.
    """
    sql = "DELETE FROM group_time_link WHERE group_key=%s"
    with _cursor() as (conn, cur):
        cur.execute(sql, (group_key,))
        return cur.rowcount > 0

def get_link(group_key: str) -> Optional[str]:
    """
    Возвращает time_group_key по group_key или None, если связи нет.
    """
    sql = "SELECT time_group_key FROM group_time_link WHERE group_key=%s"
    with _cursor() as (conn, cur):
        cur.execute(sql, (group_key,))
        row = cur.fetchone()
        return row[0] if row else None

def find_by_time_group(time_group_key: str) -> Optional[Dict]:
    """
    Ищет и возвращает полную запись по time_group_key в виде словаря:
      { "group_key": str, "time_group_key": str, "linked_at": datetime }
    Возвращает None, если запись не найдена.
    """
    sql = "SELECT group_key, time_group_key, linked_at FROM group_time_link WHERE time_group_key=%s"
    with _cursor() as (conn, cur):
        cur.execute(sql, (time_group_key,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(group_key=row[0], time_group_key=row[1], linked_at=row[2])
