# /home/telegrambot/shift_tracker_bot/database/duty_repository.py
# -*- coding: utf-8 -*-
"""
Репозиторий для работы с дежурствами (duties) и их назначениями.
Содержит CRUD по duties, выборки назначений, и алгоритмы авто-распределения:
- по дате (fair-load),
- по дате RR,
- по текущему времени RR (учёт окон слотов + исключений).

Источник правды по списку обязанностей — КАТАЛОГ (таблица duty).
Перед любым авто-распределением выполняется синхронизация каталога → duties (UPSERT по code=key).
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import date, datetime, time
import logging
from zoneinfo import ZoneInfo
from .connection import db_connection
from database import time_repository as time_repo
from .duty_catalog_repository import fetch_catalog  # NEW: читаем каталог

from .duty_admin_repository import (
    get_member_rank, is_user_excluded_on, get_rr_last, set_rr_last
)

logger = logging.getLogger(__name__)

def _allowed_rank_range(duty: Dict[str, Any]) -> range:
    """Диапазон рангов из каталога (включительно): [target_rank .. min_rank]."""
    tr = duty.get("target_rank")
    mr = duty.get("min_rank")
    try:
        low = int(tr) if tr is not None else 1
    except Exception:
        low = 1
    try:
        high = int(mr) if mr is not None else 3
    except Exception:
        high = 3
    if low > high:
        low, high = high, low
    return range(low, high + 1)

def _eligible_for_catalog_duty(user_rank: int, duty: Dict[str, Any]) -> bool:
    """Пользователь подходит только если его ранг попадает в допустимый диапазон."""
    return int(user_rank) in _allowed_rank_range(duty)

def _catalog_bounds_map() -> Dict[str, tuple[int, int]]:
    """Кэш: key -> (target_rank, min_rank), нормализовано по возрастанию."""
    m: Dict[str, tuple[int, int]] = {}
    try:
        for c in fetch_catalog() or []:
            key = str(c.get("key") or "").strip()
            if not key:
                continue
            tr = int(c.get("target_rank") or 1)
            mr = int(c.get("min_rank") or 3)
            if tr > mr:
                tr, mr = mr, tr
            m[key] = (tr, mr)
    except Exception:
        logger.exception("catalog bounds fetch failed")
    return m

def _duty_bounds_for_row(duty_row: Dict[str, Any], bounds_map: Dict[str, tuple[int,int]]) -> tuple[int,int]:
    """Возвращает (target_rank, min_rank) для duty_row, приоритет из каталога."""
    code = (duty_row.get("code") or "").strip()
    if code and code in bounds_map:
        return bounds_map[code]
    try:
        mr = int(duty_row.get("min_rank") or 3)
    except Exception:
        mr = 3
    tr = 1
    if tr > mr:
        tr, mr = mr, tr
    return (tr, mr)

def _is_eligible_by_range(emp_rank: int, tr: int, mr: int) -> bool:
    """Проверка: emp_rank в диапазоне [target_rank..min_rank]."""
    try:
        er = int(emp_rank)
        return int(tr) <= er <= int(mr)
    except Exception:
        return False

def _name_for_member(m: Dict[str, Any]) -> str:
    fn = (m.get("first_name") or "").strip()
    ln = (m.get("last_name") or "").strip()
    if fn or ln:
        return f"{fn} {ln}".strip()
    u = (m.get("username") or "").strip()
    return f"@{u}" if u else str(m.get("user_id"))


def _derive_kind_from_ranks(target_rank: Optional[int], min_rank: Optional[int]) -> str:
    """
    Маппинг каталога в kind (leader/specialist/junior) для таблицы duties.
      - если target_rank == 1 → leader
      - иначе если (min_rank или target_rank) <= 2 → specialist
      - иначе → junior
    """
    try:
        t = int(target_rank) if target_rank is not None else None
    except Exception:
        t = None
    try:
        m = int(min_rank) if min_rank is not None else None
    except Exception:
        m = None

    if t == 1:
        return "leader"
    thr = m if m is not None else t
    if thr is not None and thr <= 2:
        return "specialist"
    return "junior"

# ----------------- ВСПОМОГАТЕЛЬНОЕ -----------------

def _get_base_pos(m: dict) -> int:
    for k in ("base_pos", "pos", "position", "slot_pos"):
        v = m.get(k)
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return 0

def _member_rank(m: Dict[str, Any], group_key: Optional[str]) -> int:
    try:
        if group_key:
            r = get_member_rank(str(group_key), int(m.get("user_id")))
            if r in (1, 2, 3):
                return r
    except Exception:
        pass
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

def _last_load_for_users(group_key: str, duty_id: int, since_days: int = 30) -> Dict[int, int]:
    sql = """
        SELECT user_id, COUNT(*) AS cnt
        FROM duty_assignments
        WHERE group_key=%s AND duty_id=%s AND on_date >= CURRENT_DATE - %s::INTERVAL
        GROUP BY user_id
    """
    res: Dict[int, int] = {}
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(sql, (group_key, duty_id, f"{since_days} days"))
            for uid, cnt in cur.fetchall():
                res[int(uid)] = int(cnt)
    except Exception:
        pass
    return res

def _parse_time_like(v) -> Optional[time]:
    try:
        if v is None:
            return None
        if isinstance(v, time):
            return v
        if isinstance(v, int):
            h, m = divmod(v, 60)
            return time(int(h), int(m))
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            parts = s.split(":")
            if len(parts) == 2:
                hh, mm = int(parts[0]), int(parts[1])
                return time(hh, mm)
            if len(parts) == 3:
                hh, mm, ss = int(parts[0]), int(parts[1]), int(parts[2])
                return time(hh, mm, ss)
            if s.isdigit():
                return _parse_time_like(int(s))
            return None
        if isinstance(v, dict):
            if "h" in v or "hour" in v or "m" in v or "min" in v:
                hh = int(v.get("h", v.get("hour", 0)))
                mm = int(v.get("m", v.get("min", 0)))
                ss = int(v.get("s", v.get("sec", 0)))
                return time(hh, mm, ss)
            return None
    except Exception:
        logger.exception("time parse failed for %r", v)  # LOG
    return None

def plan_duties_now_weighted(now_local: datetime, group_key: Optional[str] = None) -> Dict[str, Any]:
    """
    НЕ пишет в БД. Строит план распределения АКТИВНОГО каталога обязанностей
    между сотрудниками, кто действительно в смене СЕЙЧАС, с выравниванием по суммарному весу.
    Возвращает структуру:
    {
      "<group_key>": {
         "members": [{"user_id":..,"name":..,"rank":..,"weight":<sum>,"duties":[<каталожные ключи/заголовки>]}],
         "idle": [<группы без смены> — только если group_key не задан],
      },
      ...
    }
    """
    # 1) какие группы сейчас активны
    groups = time_repo.list_groups() or []
    if group_key:
        groups = [g for g in groups if str(g.get("key")) == str(group_key)]

    # 2) активный каталог (источник правды)
    catalog = fetch_catalog()  # только is_active=TRUE
    # Сортируем по убыванию веса, чтобы "тяжелые" задания раскладывать первыми
    catalog_sorted = sorted(catalog, key=lambda d: int(d.get("weight") or 0), reverse=True)

    result: Dict[str, Any] = {}
    groups_with_no_shift: list[str] = []

    for g in groups:
        key = str(g["key"])
        info = time_repo.get_group_info(key)
        if not info:
            continue

        # 3) кто прямо сейчас реально в смене (учет окна)
        on_now = _on_duty_members_now(info, now_local)
        if not on_now:
            groups_with_no_shift.append(key)
            continue

        # корзина сотрудников с текущей суммой веса и списком назначенных каталожных задач
        bucket = []
        for m in on_now:
            r = _member_rank(m, key)
            bucket.append({
                "user_id": int(m["user_id"]),
                "name": _name_for_member(m),
                "rank": r,
                "sum_weight": 0,
                "duties": []
            })

        # вспомогательный индекс по user_id
        by_uid = {b["user_id"]: b for b in bucket}

        # 4) распределяем каталог (тяжёлые вперёд) с дедупликацией по key
        seen_keys: set[str] = set()

        for d in catalog_sorted:
            k = str(d.get("key") or "").strip()
            if not k:
                # на всякий случай пропустим безключевые записи
                continue
            if k in seen_keys:
                continue
            weight = int(d.get("weight") or 0)

            # фильтр по рангу (строго по диапазону)
            candidates = [b for b in bucket if _eligible_for_catalog_duty(b["rank"], d)]
            if not candidates:
                continue

            # берём с минимальной текущей нагрузкой (тай-брейк — по имени)
            candidates.sort(key=lambda b: (b["sum_weight"], b["name"].lower()))
            target = candidates[0]

            # защита от дублей внутри одного сотрудника (если в каталоге дубликаты title)
            title = d.get("title") or k
            if title in target["duties"]:
                continue

            target["duties"].append(title)
            target["sum_weight"] += weight
            seen_keys.add(k)

        # 5) записываем в результат
        result[key] = {
            "members": sorted(bucket, key=lambda b: b["name"].lower())
        }

    # если по всем группам хотим вывести «кто не работает»
    if not group_key:
        result["_idle_groups"] = groups_with_no_shift

    return result

def _on_duty_members_now(info: Dict[str, Any], now_local: datetime) -> List[Dict[str, Any]]:
    """Участники, которые должны работать ПРЯМО СЕЙЧАС (слот + исключения + окно времени, всё в MSK)."""
    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    members = info.get("members", [])
    res: List[Dict[str, Any]] = []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    slots = info.get("slots", [])
    group_key = info.get("key") or info.get("name")

    logger.debug(
        "duty_repo.on_now: group=%s period=%s epoch=%s members_total=%d",
        group_key, period, epoch, len(members)
    )

    for m in members:
        base_pos = _get_base_pos(m)

        # Определяем индекс активного слота по дате (MSK)
        if period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, 8, base_pos, now_local.date())
        else:
            slot_idx = resolve4(epoch, 4, base_pos, now_local.date())

        if slot_idx is None:
            logger.debug("duty_repo.on_now: skip uid=%s reason=no_slot_idx", m.get("user_id"))
            continue

        slot = next((s for s in slots if s.get("pos") == slot_idx), None)
        uid = int(m.get("user_id"))

        # Исключения (отпуск/болезнь)
        if is_user_excluded_on(str(group_key), uid, now_local.date()):
            logger.debug("duty_repo.on_now: skip uid=%s reason=excluded", uid)
            continue

        # Проверка попадания текущего времени в окно слота
        in_window = _is_now_in_window(now_local, slot)
        logger.debug("duty_repo.on_now: uid=%s slot_idx=%s in_window=%s slot=%r", uid, slot_idx, in_window, slot)
        if not in_window:
            logger.debug("duty_repo.on_now: skip uid=%s reason=out_of_window", uid)
            continue

        mm = dict(m)
        mm["_slot_idx"] = slot_idx
        mm["_slot"] = slot
        res.append(mm)

    logger.debug("duty_repo.on_now: group=%s active_now=%d", group_key, len(res))
    return res

def _is_now_in_window(now_local: datetime, slot: Optional[dict]) -> bool:
    # Если слота нет — считаем «закрыто» (иначе прилетят лишние назначения)
    if slot is None:
        return False

    t0, t1 = _slot_time_window(slot)

    # Если нет явных границ — тоже закрыто
    if t0 is None and t1 is None:
        return False

    cur = now_local.time()
    if t0 is None:
        return cur <= t1
    if t1 is None:
        return cur >= t0
    if t0 <= t1:
        return t0 <= cur <= t1
    return cur >= t0 or cur <= t1  # ночная смена

def sync_catalog_to_duties(deactivate_missing: bool = False) -> int:
    """
    Зеркалируем все записи из каталога (таблица duty) в duties (UPSERT по code=key).
    Возвращает количество обработанных записей.
    Если deactivate_missing=True — те записи в duties, которых нет в каталоге, деактивируем (is_active=FALSE).
    """
    cats = fetch_catalog(search=None, limit=5000)  # активные из каталога
    keys_in_cat = {c["key"] for c in cats}
    changed = 0

    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        for c in cats:
            code = c["key"]
            title = c.get("title")
            desc = c.get("description")
            kind = _derive_kind_from_ranks(c.get("target_rank"), c.get("min_rank"))
            min_rank = int(c.get("min_rank") or 2)
            is_active = bool(c.get("is_active", True))

            cur.execute(
                """
                INSERT INTO duties (code, title, description, kind, min_rank, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE
                   SET title=EXCLUDED.title,
                       description=EXCLUDED.description,
                       kind=EXCLUDED.kind,
                       min_rank=EXCLUDED.min_rank,
                       is_active=EXCLUDED.is_active,
                       updated_at=NOW()
                """,
                (code, title, desc, kind, min_rank, is_active)
            )
            changed += 1

        if deactivate_missing:
            if keys_in_cat:
                cur.execute(
                    "UPDATE duties SET is_active=FALSE WHERE code IS NOT NULL AND code <> '' AND code NOT IN %s",
                    (tuple(keys_in_cat),)
                )
            else:
                # каталог пуст — отключать ничего не будем, чтобы не выключить всё случайно
                pass

        conn.commit()
    return changed

def _on_duty_members(info: Dict[str, Any], on_date: date) -> List[Dict[str, Any]]:
    """Участники, которые должны дежурить в указанную дату, с учётом исключений."""
    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    members = info.get("members", [])
    res: List[Dict[str, Any]] = []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    slots = info.get("slots", [])
    group_key = info.get("key") or info.get("name")

    for m in members:
        base_pos = _get_base_pos(m)
        if period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, 8, base_pos, on_date)
        else:
            slot_idx = resolve4(epoch, 4, base_pos, on_date)
        if slot_idx is None:
            continue

        uid = int(m.get("user_id"))
        if is_user_excluded_on(str(group_key), uid, on_date):
            continue

        mm = dict(m)
        mm["_slot_idx"] = slot_idx
        mm["_slot"] = next((s for s in slots if s.get("pos") == slot_idx), None)
        res.append(mm)
    return res

def _rank_distance_for_duty(emp_rank: int, duty_min_rank: int) -> int:
    """
    Чем меньше значение, тем предпочтительнее.
    Для min_rank=3: emp_rank=3 -> 0 (лучше), 2 -> 1, 1 -> 2
    Для min_rank=2: emp_rank=2 -> 0 (лучше), 1 -> 1
    Для min_rank=1: emp_rank=1 -> 0 (единственный допустимый)
    """
    return int(duty_min_rank) - int(emp_rank)

def _is_eligible_by_min_rank(emp_rank: int, duty_min_rank: Optional[int]) -> bool:
    """
    ЖЁСТКОЕ соблюдение min_rank: сотрудник допустим, если emp_rank <= duty_min_rank.
    Примеры:
      duty_min_rank=1 -> только rank=1
      duty_min_rank=2 -> rank in {1,2}
      duty_min_rank=3 -> rank in {1,2,3}
    """
    try:
        mr = int(duty_min_rank) if duty_min_rank is not None else 3
        er = int(emp_rank)
        return er <= mr
    except Exception:
        return False

def _load_catalog_sorted_by_weight() -> List[Dict[str, Any]]:
    """
    Возвращает активный каталог, отсортированный по weight DESC, с безопасными полями:
      key, title, min_rank, weight
    """
    catalog = fetch_catalog()  # активные
    safe = []
    for d in catalog or []:
        safe.append({
            "key": (d.get("key") or "").strip(),
            "title": d.get("title") or (d.get("key") or ""),
            "min_rank": int(d.get("min_rank") or 3),
            "weight": int(d.get("weight") or 0),
        })
    return sorted([d for d in safe if d["key"]], key=lambda x: x["weight"], reverse=True)

def _duties_by_code_map() -> Dict[str, Dict[str, Any]]:
    """
    После sync_catalog_to_duties() в таблице duties есть строки с code=key.
    Построим индекс code -> row (чтобы получить duty_id при записи назначений).
    """
    rows = list_duties(only_active=True)
    by_code: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        code = (r.get("code") or "").strip()
        if code:
            by_code[code] = r
    return by_code

def _active_members_global_now(now_local: datetime) -> List[Dict[str, Any]]:
    groups = time_repo.list_groups() or []
    logger.debug("global_now: groups=%d now=%s", len(groups), now_local)  # LOG

    pool: Dict[int, Dict[str, Any]] = {}
    for g in groups:
        key = str(g.get("key"))
        info = time_repo.get_group_info(key)
        if not info:
            logger.debug("global_now: skip group=%s (no info)", key)  # LOG
            continue
        ms = _on_duty_members_now(info, now_local)
        logger.debug("global_now: group=%s active=%d", key, len(ms))  # LOG
        for m in ms:
            uid = int(m["user_id"])
            if uid not in pool:
                pool[uid] = {
                    "user_id": uid,
                    "name": _display_name(m),
                    "group_key": key,
                }
    logger.debug("global_now: pool_size=%d uids=%s", len(pool), sorted(pool.keys()))  # LOG
    return list(pool.values())

# --- Хелперы для дат/индекса слота ---

from datetime import datetime, date, time  # убедись, что time импортирован

def _as_date(v) -> Optional[date]:
    """Безопасно приводим epoch к date."""
    try:
        if v is None:
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, str):
            return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except Exception:
        pass
    return None

def _generic_slot_idx(epoch: Optional[date], n_slots: int, base_pos: int, on_date: date) -> int:
    """Универсальный индекс слота по модулю длины цикла (fallback для period≠4/8)."""
    if n_slots <= 0:
        return 0
    ep = _as_date(epoch) or on_date  # если нет эпохи — «не двигаем» цикл
    days = (on_date - ep).days
    try:
        return int((base_pos + (days % n_slots)) % n_slots)
    except Exception:
        return 0


# --------- ВРЕМЕННЫЕ ОКНА ---------

def _slot_time_window(slot: Optional[dict]) -> Tuple[Optional[time], Optional[time]]:
    if not slot:
        return (None, None)

    pairs = [
        ("start", "end"),
        ("from", "to"),
        # популярные синонимы
        ("time_from", "time_to"),
        ("begin", "finish"),
        ("begin_time", "finish_time"),
        ("start_time", "end_time"),
        ("from_time", "to_time"),
    ]
    for a, b in pairs:
        if a in slot or b in slot:
            t0, t1 = _parse_time_like(slot.get(a)), _parse_time_like(slot.get(b))
            logger.debug("slot window via %s/%s -> %s..%s; raw=%r", a, b, t0, t1, slot)
            return (t0, t1)

    hours = slot.get("hours")
    if isinstance(hours, dict):
        t0, t1 = _parse_time_like(hours.get("start")), _parse_time_like(hours.get("end"))
        logger.debug("slot window via hours.start/end -> %s..%s; raw=%r", t0, t1, slot)
        return (t0, t1)

    if "start_min" in slot or "end_min" in slot:
        t0, t1 = _parse_time_like(slot.get("start_min")), _parse_time_like(slot.get("end_min"))
        logger.debug("slot window via *_min -> %s..%s; raw=%r", t0, t1, slot)
        return (t0, t1)

    logger.debug("slot window: none; raw=%r", slot)
    return (None, None)


# --------- ПУЛ УЧАСТНИКОВ «НА СЕЙЧАС» ---------

def _on_duty_members_now(info: Dict[str, Any], now_local: datetime) -> List[Dict[str, Any]]:
    """Кто должен работать ПРЯМО СЕЙЧАС (учёт исключений и временных окон)."""
    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    members = info.get("members", [])
    res: List[Dict[str, Any]] = []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    slots = info.get("slots", []) or []
    group_key = info.get("key") or info.get("name")

    logger.debug(
        "duty_repo.on_now: group=%s period=%s epoch=%s members_total=%d",
        group_key, period, epoch, len(members)
    )

    for m in members:
        base_pos = _get_base_pos(m)

        # Вычисляем индекс активного слота
        if len(slots) == 1:
            slot_idx = slots[0].get("pos", 0) or 0
        elif period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, 8, base_pos, now_local.date())
        elif period == 4:
            slot_idx = resolve4(epoch, 4, base_pos, now_local.date())
        else:
            n_slots = len({s.get("pos") for s in slots}) or max(1, period)
            slot_idx = _generic_slot_idx(_as_date(epoch), n_slots, base_pos, now_local.date())

        if slot_idx is None:
            logger.debug("duty_repo.on_now: skip uid=%s reason=no_slot_idx", m.get("user_id"))
            continue

        slot = next((s for s in slots if s.get("pos") == slot_idx), None)
        if slot is None and len(slots) == 1:
            slot = slots[0]

        uid = int(m.get("user_id"))

        # Исключения (отпуск/болезнь)
        if is_user_excluded_on(str(group_key), uid, now_local.date()):
            logger.debug("duty_repo.on_now: skip uid=%s reason=excluded", uid)
            continue

        # Проверка попадания текущего времени в окно слота
        in_window = _is_now_in_window(now_local, slot)
        logger.debug("duty_repo.on_now: uid=%s slot_idx=%s in_window=%s slot=%r", uid, slot_idx, in_window, slot)
        if not in_window:
            logger.debug("duty_repo.on_now: skip uid=%s reason=out_of_window", uid)
            continue

        mm = dict(m)
        mm["_slot_idx"] = slot_idx
        mm["_slot"] = slot
        res.append(mm)

    logger.debug("duty_repo.on_now: group=%s active_now=%d", group_key, len(res))
    return res

def get_on_duty_members_now(group_key: str, now_local: datetime) -> List[Dict[str, Any]]:
    """Участники «на сейчас» по ключу группы."""
    info = time_repo.get_group_info(str(group_key))
    if not info:
        return []
    return _on_duty_members_now(info, now_local)


def get_on_duty_members_now_debug(group_key: str, now_local: datetime) -> Dict[str, Any]:
    """
    Отладка: {'ok': [members], 'skipped': [{'user_id':..,'name':..,'reason':..}, ...]}
    Причины: 'no_slot_idx' | 'excluded' | 'out_of_window [HH:MM..HH:MM]'
    """
    info = time_repo.get_group_info(str(group_key))
    if not info:
        return {"ok": [], "skipped": []}

    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    members = info.get("members", [])
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    slots = info.get("slots", []) or []

    res_ok: List[Dict[str, Any]] = []
    res_skip: List[Dict[str, Any]] = []

    def _nm(m: dict) -> str:
        fn = (m.get("first_name") or "").strip()
        ln = (m.get("last_name") or "").strip()
        if fn or ln:
            return f"{fn} {ln}".strip()
        u = (m.get("username") or "").strip()
        return f"@{u}" if u else str(m.get("user_id"))

    for m in members:
        uid = int(m.get("user_id"))
        base_pos = _get_base_pos(m)
        # индекс слота
        if len(slots) == 1:
            slot_idx = slots[0].get("pos", 0) or 0
        elif period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, 8, base_pos, now_local.date())
        elif period == 4:
            slot_idx = resolve4(epoch, 4, base_pos, now_local.date())
        else:
            n_slots = len({s.get("pos") for s in slots}) or max(1, period)
            slot_idx = _generic_slot_idx(_as_date(epoch), n_slots, base_pos, now_local.date())

        if slot_idx is None:
            res_skip.append({"user_id": uid, "name": _nm(m), "reason": "no_slot_idx"})
            continue

        slot = next((s for s in slots if s.get("pos") == slot_idx), None)
        if slot is None and len(slots) == 1:
            slot = slots[0]

        if is_user_excluded_on(str(info.get("key") or info.get("name")), uid, now_local.date()):
            res_skip.append({"user_id": uid, "name": _nm(m), "reason": "excluded"})
            continue

        if not _is_now_in_window(now_local, slot):
            t0, t1 = _slot_time_window(slot)
            def _fmt(t):
                return t.isoformat(timespec="minutes") if isinstance(t, time) else "—"
            res_skip.append({"user_id": uid, "name": _nm(m), "reason": f"out_of_window [{_fmt(t0)}..{_fmt(t1)}]"})
            continue

        mm = dict(m)
        mm["_slot_idx"] = slot_idx
        mm["_slot"] = slot
        res_ok.append(mm)

    return {"ok": res_ok, "skipped": res_skip}


# --------- ПУЛ УЧАСТНИКОВ «ПО ДАТЕ» ---------

def _on_duty_members(info: Dict[str, Any], on_date: date) -> List[Dict[str, Any]]:
    """Кто должен дежурить в указанную дату (учёт исключений)."""
    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    members = info.get("members", [])
    res: List[Dict[str, Any]] = []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    slots = info.get("slots", []) or []
    group_key = info.get("key") or info.get("name")

    for m in members:
        base_pos = _get_base_pos(m)

        if len(slots) == 1:
            slot_idx = slots[0].get("pos", 0) or 0
        elif period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, 8, base_pos, on_date)
        elif period == 4:
            slot_idx = resolve4(epoch, 4, base_pos, on_date)
        else:
            n_slots = len({s.get("pos") for s in slots}) or max(1, period)
            slot_idx = _generic_slot_idx(_as_date(epoch), n_slots, base_pos, on_date)

        if slot_idx is None:
            continue

        uid = int(m.get("user_id"))
        if is_user_excluded_on(str(group_key), uid, on_date):
            continue

        mm = dict(m)
        mm["_slot_idx"] = slot_idx
        sl = next((s for s in slots if s.get("pos") == slot_idx), None)
        if sl is None and len(slots) == 1:
            sl = slots[0]
        mm["_slot"] = sl
        res.append(mm)
    return res


def count_on_shift_now(now_local: datetime, group_key: Optional[str] = None) -> int:
    groups = time_repo.list_groups() or []
    if group_key:
        groups = [g for g in groups if str(g.get("key")) == str(group_key)]
    total = 0
    for g in groups:
        info = time_repo.get_group_info(str(g["key"]))
        if not info:
            continue
        total += len(_on_duty_members_now(info, now_local))
    return total


def auto_assign_for_date(on_date: date, author_id: Optional[int] = None, group_key: Optional[str] = None) -> int:
    # NEW: синхронизация каталога → duties
    try:
        sync_catalog_to_duties(deactivate_missing=False)
    except Exception:
        logger.exception("catalog sync failed (continue)")

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
            if d["kind"] == "leader":
                pool = [m for m in on_duty if _member_rank(m, key) <= 1]
            else:
                pool = [m for m in on_duty if _member_rank(m, key) <= int(d.get("min_rank") or 2)]
            if not pool:
                continue

            last_load = _last_load_for_users(key, d["id"], since_days=30)
            pool_sorted = sorted(
                pool,
                key=lambda m: (last_load.get(int(m.get("user_id")), 0), _display_name(m).lower())
            )
            target_uid = int(pool_sorted[0]["user_id"])

            if set_assignment(d["id"], key, on_date, target_uid, author_id):
                total += 1

    return total

def auto_assign_for_date_rr(on_date: date, author_id: Optional[int] = None, group_key: Optional[str] = None) -> int:
    # NEW: синхронизация каталога → duties
    try:
        sync_catalog_to_duties(deactivate_missing=False)
    except Exception:
        logger.exception("catalog sync failed (continue)")

    duties = list_duties(only_active=True)
    if not duties:
        return 0
    bounds_map = _catalog_bounds_map()
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

        used_users: set[int] = set()  # не повторяем исполнителя в группе за день

        duties_sorted = sorted(duties, key=lambda d: (0 if d["kind"]=="leader" else 1, d["id"]))

        for d in duties_sorted:
            if not d["is_active"]:
                continue

            eligible = []
            for m in on_duty:
                r = _member_rank(m, key)
                ok = (r <= 1) if d["kind"] == "leader" else (r <= int(d.get("min_rank") or 2))
                if ok:
                    eligible.append(int(m["user_id"]))

            if not eligible:
                continue

            eligible_no_reuse = [u for u in sorted(set(eligible)) if u not in used_users]
            pool = eligible_no_reuse or sorted(set(eligible))

            last = get_rr_last(key, d["id"])
            if last is None or last not in pool:
                nxt = pool[0]
            else:
                i = pool.index(last)
                nxt = pool[(i + 1) % len(pool)]

            if set_assignment(d["id"], key, on_date, nxt, author_id):
                set_rr_last(key, d["id"], nxt)
                used_users.add(nxt)
                total += 1

    return total

def auto_assign_for_datetime_rr(now_local: datetime, author_id: Optional[int] = None, group_key: Optional[str] = None) -> int:
    # 1) синхронизация каталога -> duties
    try:
        sync_catalog_to_duties(deactivate_missing=False)
    except Exception:
        logger.exception("catalog sync failed (continue)")

    duties = list_duties(only_active=True)
    groups = time_repo.list_groups() or []
    if group_key:
        groups = [g for g in groups if str(g.get("key")) == str(group_key)]
    logger.debug("duty_repo.assign_now: groups=%d duties=%d now=%s", len(groups), len(duties), now_local)

    total = 0

    for g in groups:
        key = str(g["key"])
        info = time_repo.get_group_info(key)
        if not info:
            logger.debug("duty_repo.assign_now: group=%s no_info", key)
            continue

        # кто реально «на сейчас» (учёт окон слотов и исключений)
        on_duty = _on_duty_members_now(info, now_local)
        logger.debug("duty_repo.assign_now: group=%s on_now=%d", key, len(on_duty))
        if not on_duty:
            continue

        used_users: set[int] = set()

        # лидеров назначаем первыми, чтобы зарезервировать rank=1
        duties_sorted = sorted(duties, key=lambda d: (0 if d["kind"] == "leader" else 1, d["id"]))

        for d in duties_sorted:
            if not d["is_active"]:
                continue

            # кандидаты по рангу в текущей группе
            eligible: list[int] = []
            for m in on_duty:
                r = _member_rank(m, key)
                ok = (r <= 1) if d["kind"] == "leader" else (r <= int(d.get("min_rank") or 2))
                if ok:
                    eligible.append(int(m["user_id"]))
                else:
                    logger.debug(
                        "duty_repo.assign_now: duty=%s min_rank=%s skip uid=%s rank=%s",
                        d.get("code") or d.get("title"), d.get("min_rank"), m.get("user_id"), r
                    )

            if not eligible:
                logger.debug("duty_repo.assign_now: group=%s duty=%s no_eligible", key, d.get("code") or d.get("title"))
                continue

            # стараться не повторять пользователя в группе за один прогон
            pool = [u for u in sorted(set(eligible)) if u not in used_users] or sorted(set(eligible))

            # round-robin: двигаем по последнему исполнителю
            last = get_rr_last(key, d["id"])
            if last is None or last not in pool:
                nxt = pool[0]
            else:
                i = pool.index(last)
                nxt = pool[(i + 1) % len(pool)]

            if set_assignment(d["id"], key, now_local.date(), nxt, author_id):
                set_rr_last(key, d["id"], nxt)
                used_users.add(nxt)
                total += 1

        logger.debug("duty_repo.assign_now: group=%s assigned_now=%d (running total=%d)", key, len(used_users), total)

    logger.debug("duty_repo.assign_now: total=%d", total)
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



def auto_assign_weighted_global_now(now_local: datetime, author_id: Optional[int] = None) -> int:
    try:
        sync_catalog_to_duties(deactivate_missing=False)
    except Exception:
        logger.exception("catalog sync failed (continue)")

    duties = list_duties(only_active=True)
    logger.debug("assignw_now: duties_active=%d", len(duties))  # LOG
    if not duties:
        return 0

    pool = _active_members_global_now(now_local)
    if not pool:
        logger.debug("assignw_now: pool empty -> 0")  # LOG
        return 0

    # собрать ранги
    buckets = []
    for p in pool:
        gk = p.get("group_key")
        uid = int(p["user_id"])
        try:
            r = get_member_rank(str(gk), uid)
        except Exception:
            r = None
        rank = int(r) if r in (1,2,3) else 2
        buckets.append({"user_id": uid, "name": p["name"], "group_key": gk, "rank": rank, "sum_weight": 0, "duties": []})
        logger.debug("assignw_now: user uid=%s name=%s group=%s rank=%s", uid, p["name"], gk, rank)  # LOG

    # веса из каталога
    try:
        cat_map = {str(c["key"]): int(c.get("weight") or 0) for c in fetch_catalog()}
    except Exception:
        cat_map = {}
    def _w(d):
        return int(cat_map.get(str(d.get("code") or ""), 0))

    duties_sorted = sorted([d for d in duties if d.get("is_active")], key=_w, reverse=True)
    logger.debug("assignw_now: duties_sorted=%d (top5 weights=%s)", len(duties_sorted), [_w(d) for d in duties_sorted[:5]])  # LOG

    total = 0
    seen_codes: set[str] = set()

    for d in duties_sorted:
        code = (d.get("code") or "").strip()
        if code and code in seen_codes:
            logger.debug("assignw_now: skip dup code=%s", code)  # LOG
            continue
        try:
            min_rank = int(d.get("min_rank") or 2)
        except Exception:
            min_rank = 2

        cand = [b for b in buckets if int(b["rank"]) <= min_rank]
        logger.debug("assignw_now: duty id=%s code=%s title=%r min_rank=%s cand=%d",
                     d.get("id"), code, d.get("title"), min_rank, len(cand))  # LOG
        if not cand:
            continue

        cand.sort(key=lambda b: (b["sum_weight"], b["name"].lower()))
        tgt = cand[0]
        title = d.get("title") or d.get("code") or f"duty#{d.get('id')}"
        if title in tgt["duties"]:
            logger.debug("assignw_now: skip same-title for uid=%s title=%r", tgt["user_id"], title)  # LOG
            continue

        gkey = tgt["group_key"] or ""
        ok = set_assignment(int(d["id"]), str(gkey), now_local.date(), int(tgt["user_id"]), author_id)
        logger.debug("assignw_now: SET duty=%s->uid=%s g=%s ok=%s w=%s",
                     d.get("id"), tgt["user_id"], gkey, ok, _w(d))  # LOG
        if ok:
            tgt["duties"].append(title)
            tgt["sum_weight"] += _w(d)
            seen_codes.add(code)
            total += 1

    logger.debug("assignw_now: total_assigned=%d", total)  # LOG
    return total

def auto_assign_weighted_for_date(on_date: date,
                                  author_id: Optional[int] = None,
                                  group_key: Optional[str] = None) -> int:
    """
    Генерирует РЕАЛЬНЫЕ назначения на указанную дату:
      - общий пул задач из каталога
      - сотрудники берутся из расписаний групп, кто в смене в этот день
      - строгий min_rank (emp_rank <= duty.min_rank)
      - балансировка по суммарному весу (тяжёлые задачи вперёд)
      - при равной нагрузке приоритет сотрудникам с рангом ближе к min_rank задачи
    Сохраняет в duty_assignments и возвращает количество записанных назначений.
    """
    # 0) синхронизация каталога -> duties (нужны id для записи)
    try:
        sync_catalog_to_duties(deactivate_missing=False)
    except Exception:
        logger.exception("catalog sync failed (continue)")

    # 1) подготовка данных
    catalog_sorted = _load_catalog_sorted_by_weight()
    if not catalog_sorted:
        return 0

    duties_map = _duties_by_code_map()  # code -> duties row (с id и min_rank)
    groups = time_repo.list_groups() or []
    if group_key:
        groups = [g for g in groups if str(g.get("key")) == str(group_key)]

    total_written = 0

    # 2) проходим по группам как по "сменам" (каталог один и тот же)
    for g in groups:
        gkey = str(g["key"])
        info = time_repo.get_group_info(gkey)
        if not info:
            continue

        # кто должен работать в этот день (учёт исключений)
        on_duty = _on_duty_members(info, on_date)
        if not on_duty:
            continue

        # корзина сотрудников с текущей суммой "весов" на ЭТУ генерацию
        bucket = []
        for m in on_duty:
            r = _member_rank(m, gkey)  # 1..3
            bucket.append({
                "user_id": int(m["user_id"]),
                "name": _display_name(m),
                "rank": int(r),
                "sum_weight": 0,
            })
        if not bucket:
            continue

        # быстрый индекс
        by_uid: Dict[int, Dict[str, Any]] = {b["user_id"]: b for b in bucket}

        # 3) раскладываем каталог по сотрудникам с учётом min_rank
        for d in catalog_sorted:
            code = d["key"]
            duty_row = duties_map.get(code)
            if not duty_row:
                # на всякий — если нет соответствия в duties, пропускаем
                continue

            duty_id = int(duty_row["id"])
            duty_min_rank = int(d.get("min_rank") or duty_row.get("min_rank") or 3)
            weight = int(d.get("weight") or 0)

            # кандидаты: строго по min_rank
            candidates = [b for b in bucket if _is_eligible_by_min_rank(b["rank"], duty_min_rank)]
            if not candidates:
                continue

            # сортировка кандидатов:
            #   1) по текущей сумме весов (минимум лучше),
            #   2) по расстоянию ранга до min_rank (0 лучше),
            #   3) по имени (стабильно)
            candidates.sort(
                key=lambda b: (b["sum_weight"],
                               _rank_distance_for_duty(b["rank"], duty_min_rank),
                               b["name"].lower())
            )
            target = candidates[0]

            # 4) пишем назначение в БД (на дату, в текущую группу, исполнителя — user_id)
            ok = set_assignment(duty_id, gkey, on_date, int(target["user_id"]), author_id)
            if ok:
                # учитываем вес для балансировки следующих задач
                target["sum_weight"] += weight
                total_written += 1

    return total_written

def auto_assign_weighted_for_datetime(now_local: datetime,
                                      author_id: Optional[int] = None,
                                      group_key: Optional[str] = None) -> int:
    """
    То же самое, но с учётом ОКОН времени слота «на сейчас».
    Пишет назначения на сегодняшнюю дату now_local.date().
    """
    # 0) синхронизация каталога -> duties
    try:
        sync_catalog_to_duties(deactivate_missing=False)
    except Exception:
        logger.exception("catalog sync failed (continue)")

    catalog_sorted = _load_catalog_sorted_by_weight()
    if not catalog_sorted:
        return 0

    duties_map = _duties_by_code_map()
    groups = time_repo.list_groups() or []
    if group_key:
        groups = [g for g in groups if str(g.get("key")) == str(group_key)]

    total_written = 0
    on_date = now_local.date()

    for g in groups:
        gkey = str(g["key"])
        info = time_repo.get_group_info(gkey)
        if not info:
            continue

        # именно «на сейчас» (окна времени + исключения)
        on_now = _on_duty_members_now(info, now_local)
        if not on_now:
            continue

        bucket = []
        for m in on_now:
            r = _member_rank(m, gkey)
            bucket.append({
                "user_id": int(m["user_id"]),
                "name": _display_name(m),
                "rank": int(r),
                "sum_weight": 0,
            })
        if not bucket:
            continue

        for d in catalog_sorted:
            code = d["key"]
            duty_row = duties_map.get(code)
            if not duty_row:
                continue

            duty_id = int(duty_row["id"])
            duty_min_rank = int(d.get("min_rank") or duty_row.get("min_rank") or 3)
            weight = int(d.get("weight") or 0)

            candidates = [b for b in bucket if _is_eligible_by_min_rank(b["rank"], duty_min_rank)]
            if not candidates:
                continue

            candidates.sort(
                key=lambda b: (b["sum_weight"],
                               _rank_distance_for_duty(b["rank"], duty_min_rank),
                               b["name"].lower())
            )
            target = candidates[0]

            if set_assignment(duty_id, gkey, on_date, int(target["user_id"]), author_id):
                target["sum_weight"] += weight
                total_written += 1

    return total_written

def set_assignment_global(duty_id: int, on_date: date, user_id: int, group_key: str, author_id: Optional[int]) -> bool:
    """
    Глобальная запись: на одну задачу (duty_id) за один день может быть только один исполнитель,
    независимо от group_key. Сначала удаляем все старые, потом вставляем одну запись.
    """
    conn = db_connection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM duty_assignments WHERE duty_id=%s AND on_date=%s", (duty_id, on_date))
            cur.execute("""
                INSERT INTO duty_assignments (duty_id, group_key, on_date, user_id, created_by)
                VALUES (%s, %s, %s, %s, %s)
            """, (duty_id, group_key, on_date, user_id, author_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.exception(e)
        return False

def reconcile_weighted_global_now(now_local: datetime, author_id: Optional[int] = None) -> Dict[str, int]:
    """
    Мягкая синхронизация назначений на сегодня:
      keep: если текущий исполнитель активен и допустим по min_rank
      reassign: снятые задачи перераспределяем на активных
    Возвращает счётчик {'kept': X, 'reassigned': Y, 'skipped': Z}
    """
    stats = {'kept': 0, 'reassigned': 0, 'skipped': 0}
    # sync каталог -> duties
    try:
        sync_catalog_to_duties(deactivate_missing=False)
    except Exception:
        logger.exception("catalog sync failed (continue)")

    on_date = now_local.date()
    catalog_sorted = _load_catalog_sorted_by_weight()
    if not catalog_sorted:
        return stats
    duties_map = _duties_by_code_map()

    # 2) активные сейчас (глобально, по всем группам)
    active = _active_members_global_now(now_local)
    if not active:
        return stats

    # соберём ранги активных (по их группе)
    by_uid: Dict[int, Dict[str, Any]] = {}
    for p in active:
        uid = int(p["user_id"])
        gk = str(p.get("group_key") or "")
        try:
            r = get_member_rank(gk, uid)
        except Exception:
            r = None
        rank = int(r) if r in (1, 2, 3) else 2
        by_uid[uid] = {
            "user_id": uid,
            "name": p["name"],
            "group_key": gk,
            "rank": rank,
            "sum_weight": 0,
        }
    active_uids = set(by_uid.keys())

    # текущие назначения на сегодня (по всем группам)
    existing = get_assignments(on_date)  # у вас уже есть
    # построим index: duty_id -> (user_id, group_key)
    exist_by_duty: Dict[int, Tuple[int, str]] = {}
    for r in existing:
        exist_by_duty[int(r["duty_id"])] = (int(r["user_id"]), str(r["group_key"]))

    # 1) посчитаем текущую нагрузку по уже назначенным у активных
    dutyid_to_weight = {}
    for d in catalog_sorted:
        duty_row = duties_map.get(d["key"])
        if duty_row:
            dutyid_to_weight[int(duty_row["id"])] = int(d.get("weight") or 0)

    for r in existing:
        uid = int(r["user_id"])
        if uid in by_uid:
            by_uid[uid]["sum_weight"] += int(dutyid_to_weight.get(int(r["duty_id"]), 0))

    # 2) проходим по каталогу — решаем, оставить или перераспределить
    for d in catalog_sorted:
        code = d["key"]
        duty_row = duties_map.get(code)
        if not duty_row:
            continue
        duty_id = int(duty_row["id"])
        duty_min_rank = int(d.get("min_rank") or duty_row.get("min_rank") or 3)
        weight = int(d.get("weight") or 0)

        keep = False
        if duty_id in exist_by_duty:
            cur_uid, _cur_gk = exist_by_duty[duty_id]
            # если текущий исполнитель активен и допустим — сохраняем
            if cur_uid in active_uids and _is_eligible_by_min_rank(by_uid[cur_uid]["rank"], duty_min_rank):
                keep = True

        if keep:
            stats['kept'] += 1
            continue

        # нужен новый исполнитель
        candidates = [b for b in by_uid.values() if _is_eligible_by_min_rank(b["rank"], duty_min_rank)]
        if not candidates:
            stats['skipped'] += 1
            continue

        candidates.sort(key=lambda b: (
            b["sum_weight"],
            _rank_distance_for_duty(b["rank"], duty_min_rank),
            b["name"].lower()
        ))
        target = candidates[0]
        if set_assignment_global(duty_id, on_date, target["user_id"], target["group_key"], author_id):
            target["sum_weight"] += weight
            stats['reassigned'] += 1

    return stats
