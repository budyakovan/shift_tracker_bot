# /home/telegrambot/shift_tracker_bot/database/shift_repository.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, date, time as dtime
import logging
from zoneinfo import ZoneInfo

from .connection import db_connection

logger = logging.getLogger(__name__)

# ---------------------- утилиты времени ----------------------

def _now_localized(now: Optional[datetime], tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)

def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute

def _t_to_minutes(t: dtime) -> int:
    return t.hour * 60 + t.minute

# ---------------------- чтение из БД ----------------------

def _load_users_by_ids(user_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not user_ids:
        return {}
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(
                """
                SELECT user_id, username, first_name, last_name
                FROM users
                WHERE user_id = ANY(%s)
                """,
                (user_ids,)
            )
            rows = cur.fetchall()
        return {
            int(uid): {
                "user_id": int(uid),
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
            }
            for (uid, username, first_name, last_name) in rows
        }
    except Exception:
        logger.exception("Не удалось загрузить пользователей из users по списку id")
        return {}

def _time_group_ids_by_key(key: str) -> List[int]:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("SELECT id FROM time_groups WHERE key = %s", (key,))
            return [int(r[0]) for r in cur.fetchall()]
    except Exception:
        logger.exception("Не удалось найти time_group.id по key=%s", key)
        return []

def _user_ids_by_user_group_key(key: str) -> List[int]:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("SELECT user_id FROM user_groups WHERE group_key = %s", (key,))
            return [int(r[0]) for r in cur.fetchall()]
    except Exception:
        logger.exception("Не удалось получить user_ids из user_groups по group_key=%s", key)
        return []

def _all_tgm_user_ids() -> List[int]:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("SELECT DISTINCT user_id FROM time_group_members")
            return [int(r[0]) for r in cur.fetchall()]
    except Exception:
        logger.exception("Не удалось прочитать список user_id из time_group_members")
        return []

def _bulk_time_group_for_users(user_ids: List[int]) -> Dict[int, int]:
    if not user_ids:
        return {}
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (user_id) user_id, time_group_id
                FROM time_group_members
                WHERE user_id = ANY(%s)
                ORDER BY user_id, time_group_id
                """,
                (user_ids,)
            )
            rows = cur.fetchall()
        return {int(uid): int(tgid) for (uid, tgid) in rows}
    except Exception:
        logger.exception("Не удалось получить соответствие user_id -> time_group_id")
        return {}

def _profile_id_for_time_group(tg_id: int) -> Optional[int]:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute("SELECT profile_id FROM time_groups WHERE id = %s", (tg_id,))
            row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception:
        logger.exception("Не удалось получить profile_id для time_group_id=%s", tg_id)
        return None

def _load_profile_slots(profile_id: int) -> List[Tuple[int, int]]:
    """
    Возвращает список слотов (start_min, end_min) для данного profile_id
    из time_profile_slots, где колонки — start_time/end_time (тип TIME).
    Слоты трактуются как повторяющиеся КАЖДЫЙ ДЕНЬ.
    """
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(
                """
                SELECT start_time, end_time
                FROM time_profile_slots
                WHERE profile_id = %s
                ORDER BY pos
                """,
                (profile_id,)
            )
            rows = cur.fetchall()
        slots: List[Tuple[int, int]] = []
        for s, e in rows:
            if not isinstance(s, dtime) or not isinstance(e, dtime):
                # на всякий случай — приведём через CAST в БД, если тип неожиданен
                # но обычно сюда не попадём
                continue
            slots.append((_t_to_minutes(s), _t_to_minutes(e)))
        return slots
    except Exception:
        logger.exception("Не удалось прочитать слоты профиля (profile_id=%s) из time_profile_slots", profile_id)
        return []

# ---------------------- бизнес-логика окна ----------------------

def _is_work_window_now_by_tg_id(tg_id: int, now_local: datetime) -> bool:
    """
    Проверяем активность сейчас по time_group_id:
      time_groups.profile_id -> time_profile_slots (start_time, end_time), ЕЖЕДНЕВНО.
    Учитываем ночные окна (перехлёст через полночь).
    """
    profile_id = _profile_id_for_time_group(tg_id)
    if not profile_id:
        return False

    slots = _load_profile_slots(profile_id)
    if not slots:
        return False

    mnow = _minutes_since_midnight(now_local)

    for s, e in slots:
        if s <= e:
            # дневной слот
            if s <= mnow < e:
                return True
        else:
            # ночной слот, через полночь
            if mnow >= s or mnow < e:
                return True
    return False

# ---------------------- опциональные фильтры (заглушки безопасные) ----------------------

def _is_absent_today(user_id: int, on_date: date) -> bool:
    # Если у тебя есть таблица отсутствий — можно подключить тут.
    return False

def _is_afk_now(user_id: int) -> bool:
    # Если используется user_afk — можно добавить чтение.
    return False

def _is_office_today(user_id: int, on_date: date) -> bool:
    # Если используется location_assignments — добавь проверку.
    return False

# ---------------------- публичные функции ----------------------

def get_on_shift_now(
    now: Optional[datetime] = None,
    tz_name: str = "Europe/Moscow",
    group_key: Optional[str] = None,
    *,
    include_afk: bool = False,
    office_only: bool = False,
    return_debug: bool = False,
) -> List[Dict[str, Any]] | Dict[str, Any]:
    """
    Список «на смене сейчас» только из БД.
    group_key:
      • если соответствует time_groups.key — фильтруем по time-группе,
      • иначе — считаем это user_groups.group_key и берём её участников,
      • None — все, у кого есть запись в time_group_members.
    """
    now_local = _now_localized(now, tz_name)
    today = now_local.date()

    # выберем кандидатов
    if group_key:
        tg_ids = _time_group_ids_by_key(group_key)
        if tg_ids:
            try:
                with db_connection.get_connection().cursor() as cur:
                    cur.execute(
                        "SELECT DISTINCT user_id FROM time_group_members WHERE time_group_id = ANY(%s)",
                        (tg_ids,)
                    )
                    candidate_user_ids = [int(r[0]) for r in cur.fetchall()]
            except Exception:
                logger.exception("Не удалось получить user_id по time_group_id=%s", tg_ids)
                candidate_user_ids = []
        else:
            candidate_user_ids = _user_ids_by_user_group_key(group_key)
    else:
        candidate_user_ids = _all_tgm_user_ids()

    if not candidate_user_ids:
        result = {
            "now": now_local.isoformat(),
            "groups": [group_key] if group_key else [],
            "candidates": [],
            "on_shift": [],
            "skipped": [],
        }
        return result if return_debug else []

    users_map = _load_users_by_ids(candidate_user_ids)
    tg_by_user = _bulk_time_group_for_users(candidate_user_ids)

    on_shift: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for uid in candidate_user_ids:
        u = users_map.get(uid) or {"user_id": uid}
        reasons = []

        tg_id = tg_by_user.get(uid)
        if not tg_id or not _is_work_window_now_by_tg_id(tg_id, now_local):
            reasons.append("вне рабочего окна")

        if not include_afk and _is_afk_now(uid):
            reasons.append("AFK")

        if office_only and not _is_office_today(uid, today):
            reasons.append("не офис")

        if _is_absent_today(uid, today):
            reasons.append("отсутствие")

        if reasons:
            skipped.append({"user_id": uid, "reasons": reasons})
        else:
            on_shift.append(u)

    # сортировка по ФИО/username
    def _sort_key(rec: Dict[str, Any]) -> Tuple[str, str, int]:
        fn = (rec.get("first_name") or "").strip()
        ln = (rec.get("last_name") or "").strip()
        un = (rec.get("username") or "").strip()
        label = f"{fn} {ln}".strip() or un
        return (label.lower(), un.lower(), int(rec.get("user_id") or 0))

    on_shift.sort(key=_sort_key)

    if return_debug:
        c_list = [users_map.get(uid, {"user_id": uid}) for uid in candidate_user_ids]
        return {
            "now": now_local.isoformat(),
            "groups": [group_key] if group_key else [],
            "candidates": c_list,
            "on_shift": on_shift,
            "skipped": skipped,
        }
    return on_shift

def get_on_shift_now_debug(**kwargs) -> Dict[str, Any]:
    kwargs["return_debug"] = True
    return get_on_shift_now(**kwargs)  # type: ignore[return-value]

def is_on_shift_now(
    user_id: int,
    now: Optional[datetime] = None,
    tz_name: str = "Europe/Moscow",
    group_key: Optional[str] = None,
    *,
    include_afk: bool = False,
    office_only: bool = False,
) -> bool:
    recs = get_on_shift_now(
        now=now,
        tz_name=tz_name,
        group_key=group_key,
        include_afk=include_afk,
        office_only=office_only,
        return_debug=False,
    )
    return any(int(r.get("user_id")) == int(user_id) for r in recs)

# ------------ ШИМ для совместимости с handlers.afk_handlers ------------

def get_on_duty_members_now(
    now: Optional[datetime] = None,
    tz_name: str = "Europe/Moscow",
    group_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Совместимость с существующими импортами.
    Использует ту же логику, что и get_on_shift_now (без AFK/office-фильтров).
    """
    recs = get_on_shift_now(now=now, tz_name=tz_name, group_key=group_key)
    return recs if isinstance(recs, list) else recs.get("on_shift", [])
