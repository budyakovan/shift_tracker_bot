#cat > /home/telegrambot/shift_tracker_bot/database/duty_repository.py
# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any
from datetime import date
import logging

from .connection import db_connection
from database import time_repository as time_repo  # уже есть у вас

from .duty_admin_repository import (
    get_member_rank, is_user_excluded_on, get_rr_last, set_rr_last
)

logger = logging.getLogger(__name__)

# заменить _member_rank на версию с БД:
def _member_rank(m: Dict[str, Any], group_key: Optional[str]) -> int:
    # сначала смотрим БД
    try:
        if group_key:
            r = get_member_rank(group_key, int(m.get("user_id")))
            if r in (1,2,3):
                return r
    except Exception:
        pass
    # затем fallback из профиля группы
    try:
        return int(m.get("rank") or 2)
    except Exception:
        return 2

# скорректировать _on_duty_members — фильтр исключений:
def _on_duty_members(info: Dict[str, Any], on_date: date) -> list[Dict[str, Any]]:
    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    members = info.get("members", [])
    res = []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    slots = info.get("slots", [])
    group_key = info.get("key") or info.get("name")  # ваш ключ группы

    for m in members:
        base_pos = int(m.get("base_pos") or 0)
        if period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, 8, base_pos, on_date)
        else:
            slot_idx = resolve4(epoch, 4, base_pos, on_date)
        if slot_idx is None:
            continue

        uid = int(m.get("user_id"))
        # Исключения (включая глобальные group_key=NULL)
        if is_user_excluded_on(str(group_key), uid, on_date):
            continue

        mm = dict(m)
        mm["_slot_idx"] = slot_idx
        mm["_slot"] = next((s for s in slots if s["pos"] == slot_idx), None)
        res.append(mm)
    return res

# новый RR-алгоритм (добавить НИЖЕ существующего auto_assign_for_date, либо заменить его):
def auto_assign_for_date_rr(on_date: date, author_id: Optional[int] = None, group_key: Optional[str] = None) -> int:
    """
    Round-robin распределение: по каждой (группа,duty) берём eligible-пул
    (в смене, не исключён, проходит по min_rank) и назначаем следующего
    после last_user_id в duty_rr_cursor.
    """
    duties = list_duties(only_active=True)
    if not duties:
        return 0

    groups = time_repo.list_groups() or []
    if group_key:
        groups = [g for g in groups if str(g.get("key")) == str(group_key)]
    total = 0

    for g in groups:
        key = str(g["key"])
        info = time_repo.get_group_info(key)
        if not info:
            continue

        on_duty = _on_duty_members(info, on_date)
        if not on_duty:
            continue

        for d in duties:
            if not d["is_active"]:
                continue

            # eligible pool по рангу
            eligible = []
            for m in on_duty:
                r = _member_rank(m, key)
                if d["kind"] == "leader":
                    ok = (r <= 1)
                else:
                    ok = (r <= int(d.get("min_rank") or 2))
                if ok:
                    eligible.append(int(m["user_id"]))

            if not eligible:
                continue

            eligible = sorted(set(eligible))  # стабильный порядок
            last = get_rr_last(key, d["id"])
            nxt = None
            if last is None:
                nxt = eligible[0]
            else:
                # следующий после last в кольце
                try:
                    i = eligible.index(last)
                    nxt = eligible[(i + 1) % len(eligible)]
                except ValueError:
                    # если last больше не в пуле — начнём с первого
                    nxt = eligible[0]

            if set_assignment(d["id"], key, on_date, nxt, author_id):
                set_rr_last(key, d["id"], nxt)
                total += 1

    return total


def list_duties(kind: Optional[str] = None, only_active: bool = True) -> List[Dict[str, Any]]:
    where, params = ["1=1"], []
    if kind:
        where.append("kind=%s"); params.append(kind)
    if only_active:
        where.append("is_active=TRUE")
    sql = f"""
        SELECT id, code, title, description, kind, min_rank, is_active
        FROM duties
        WHERE {' AND '.join(where)}
        ORDER BY kind, id
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "id": r[0], "code": r[1], "title": r[2], "description": r[3],
            "kind": r[4], "min_rank": r[5], "is_active": r[6]
        } for r in rows
    ]

def create_duty(title: str, kind: str, description: Optional[str] = None,
                code: Optional[str] = None, min_rank: int = 2) -> Optional[int]:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("""
                INSERT INTO duties (code, title, description, kind, min_rank)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (code, title, description, kind, min_rank))
            new_id = cur.fetchone()[0]
            db_connection.get_connection().commit()
            return new_id
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.exception(e)
        return None

def update_duty(duty_id: int, **fields) -> bool:
    if not fields: return True
    allowed = {"code","title","description","kind","min_rank","is_active"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=%s"); params.append(v)
    if not sets: return True
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(f"UPDATE duties SET {', '.join(sets)}, updated_at=NOW() WHERE id=%s", params+[duty_id])
            db_connection.get_connection().commit()
            return cur.rowcount > 0
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.exception(e)
        return False

def delete_duty(duty_id: int) -> bool:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("DELETE FROM duties WHERE id=%s", (duty_id,))
            db_connection.get_connection().commit()
            return cur.rowcount > 0
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.exception(e)
        return False

def set_assignment(duty_id: int, group_key: str, on_date: date, user_id: int, author_id: Optional[int]) -> bool:
    """UPSERT по (duty_id, group_key, on_date)."""
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("""
                INSERT INTO duty_assignments (duty_id, group_key, on_date, user_id, created_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (duty_id, group_key, on_date) DO UPDATE SET user_id=EXCLUDED.user_id
            """, (duty_id, group_key, on_date, user_id, author_id))
            db_connection.get_connection().commit()
            return True
    except Exception as e:
        db_connection.get_connection().rollback()
        logger.exception(e)
        return False

def get_assignments(on_date: date, group_key: Optional[str] = None) -> List[Dict[str, Any]]:
    where, params = ["on_date=%s"], [on_date]
    if group_key:
        where.append("group_key=%s"); params.append(group_key)
    sql = f"""
        SELECT da.id, da.group_key, da.on_date, da.user_id,
               d.id, d.title, d.description, d.kind, d.min_rank
        FROM duty_assignments da
        JOIN duties d ON d.id = da.duty_id
        WHERE {' AND '.join(where)}
        ORDER BY da.group_key, d.kind, d.id
    """
    with db_connection.get_connection().cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "assignment_id": r[0], "group_key": r[1], "on_date": r[2], "user_id": r[3],
            "duty_id": r[4], "title": r[5], "description": r[6],
            "kind": r[7], "min_rank": r[8]
        } for r in rows
    ]

def _member_rank(m: Dict[str, Any]) -> int:
    try:
        return int(m.get("rank") or 2)
    except Exception:
        return 2

def _username(m: Dict[str, Any]) -> str:
    u = (m.get("username") or "").strip()
    return f"@{u}" if u else ""

def _display_name(m: Dict[str, Any]) -> str:
    fn = (m.get("first_name") or "").strip()
    ln = (m.get("last_name") or "").strip()
    return (f"{fn} {ln}".strip() or _username(m) or str(m.get("user_id")))

def _on_duty_members(info: Dict[str, Any], on_date: date) -> list[Dict[str, Any]]:
    """
    Возвращает участников группы, которые реально работают в on_date согласно слотам/циклам.
    Для простоты: берём всех members и отфильтровываем тех, у кого resolve даёт слот.
    """
    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    members = info.get("members", [])
    res = []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    slots = info.get("slots", [])

    for m in members:
        base_pos = int(m.get("base_pos") or 0)
        if period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, 8, base_pos, on_date)
        else:
            slot_idx = resolve4(epoch, 4, base_pos, on_date)
        if slot_idx is None:
            continue
        # найдём слот (не обязателен для решения, но пригодится)
        slot = next((s for s in slots if s["pos"] == slot_idx), None)
        mm = dict(m)
        mm["_slot_idx"] = slot_idx
        mm["_slot"] = slot
        res.append(mm)
    return res

def _last_load_for_users(group_key: str, duty_id: int, since_days: int = 30) -> Dict[int, int]:
    """
    Возвращает {user_id: кол-во назначений за N дней} для грубой справедливости (меньше — приоритетнее).
    """
    sql = """
        SELECT user_id, COUNT(*) AS cnt
        FROM duty_assignments
        WHERE group_key=%s AND duty_id=%s AND on_date >= CURRENT_DATE - %s::INTERVAL
        GROUP BY user_id
    """
    res = {}
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(sql, (group_key, duty_id, f"{since_days} days"))
            for uid, cnt in cur.fetchall():
                res[int(uid)] = int(cnt)
    except Exception:
        pass
    return res

def auto_assign_for_date(on_date: date, author_id: Optional[int] = None, group_key: Optional[str] = None) -> int:
    """
    Распределяет все активные обязанности на дату по всем группам (или одной группе),
    среди тех, кто реально в смене, учитывая kind/min_rank и простейшую справедливость по истории.
    Возвращает количество назначений.
    """
    duties = list_duties(only_active=True)
    if not duties:
        return 0

    groups = time_repo.list_groups() or []
    if group_key:
        groups = [g for g in groups if str(g.get("key")) == str(group_key)]
    total = 0

    for g in groups:
        key = g["key"]
        info = time_repo.get_group_info(key)
        if not info:
            continue

        on_duty = _on_duty_members(info, on_date)
        if not on_duty:
            continue

        # кандидаты по ролям
        leaders     = [m for m in on_duty if _member_rank(m) <= 1]
        specialists = [m for m in on_duty if _member_rank(m) <= 2]
        juniors     = [m for m in on_duty if _member_rank(m) <= 3]  # запас

        for d in duties:
            if not d["is_active"]:
                continue
            if d["kind"] == "leader":
                pool = leaders
            else:
                # specialist duty — берём всех с rank <= min_rank (обычно 2)
                pool = [m for m in on_duty if _member_rank(m) <= int(d.get("min_rank") or 2)]

            if not pool:
                continue

            # сгрубая справедливость: реже назначавшийся — приоритет
            last_load = _last_load_for_users(key, d["id"], since_days=30)
            pool_sorted = sorted(
                pool,
                key=lambda m: (last_load.get(int(m.get("user_id")), 0), _display_name(m).lower())
            )
            target_uid = int(pool_sorted[0]["user_id"])

            if set_assignment(d["id"], key, on_date, target_uid, author_id):
                total += 1

    return total
