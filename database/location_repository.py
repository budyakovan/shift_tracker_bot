# /home/telegrambot/shift_tracker_bot/database/location_repository.py
# -*- coding: utf-8 -*-
"""
Репозиторий для работы с распределением локаций (офис/дом) пользователей.
Обеспечивает автоматическое распределение рабочих мест на основе графика дежурств,
учета праздников/выходных и типа рабочих смен (дневные/ночные).

Основные функции:
- Автоматическое распределение локаций по сложным правилам (учитывает праздники, ночные смены)
- Подсчет статистики по посещениям офиса
- Round-robin алгоритм с приоритетом для тех, кто реже был в офисе
- Управление курсорами для циклического распределения
"""

from datetime import date, time, datetime, timedelta
from pytz import timezone
from typing import List, Dict, Optional, Tuple, Set, Iterable
from database.connection import db_connection
from database import time_repository as time_repo
from zoneinfo import ZoneInfo
from database.rank_repository import get_member_rank  # ранги 1..3: 1=старший спец, 2=специалист


MSK = ZoneInfo("Europe/Moscow")

def _get_rank_rotation_cfg(group_key: str) -> Optional[Tuple[date, int]]:
    """
    Читает активную конфигурацию парной ротации через rank_rotation_repository.
    Возвращает (epoch, period_days) или None, если нет/выключено.
    """
    try:
        from database.rank_rotation_repository import get_rule
        r = get_rule(str(group_key))
        if not r or not r.get("is_enabled"):
            return None
        ep = r.get("epoch")
        pd = int(r.get("period_days") or 0)
        if not ep or pd <= 0:
            return None
        return ep, pd
    except Exception:
        return None


def _safe_rank(group_key: str, user_id: int) -> int:
    """
    Безошибочно возвращает ранг участника в группе: 1..3.
    Порядок источников:
      1) duty_admin_repository.get_member_rank
      2) rank из time_repo.get_group_info(...).members
      3) дефолт 2 (специалист)
    """
    # 1) основной источник — duty_admin_repository
    try:
        r = get_member_rank(str(group_key), int(user_id))
        if r in (1, 2, 3):
            return int(r)
    except Exception:
        pass

    # 2) фолбэк — данные группы
    try:
        info = time_repo.get_group_info(str(group_key)) or {}
        for m in info.get("members", []) or []:
            if int(m.get("user_id")) == int(user_id):
                rr = m.get("rank")
                try:
                    rr = int(rr)
                    if rr in (1, 2, 3):
                        return rr
                except Exception:
                    break
    except Exception:
        pass

    # 3) дефолт
    return 2


def _pair_offset(on_date: date, epoch: date, period_days: int) -> int:
    """Смещение «партнёрских пар» относительно эпохи (0,1,2,...)"""
    try:
        return max(0, (on_date - epoch).days // int(period_days))
    except Exception:
        return 0


def _current_pairs_for_day(group_key: str, on_date: date, uids: List[int]) -> List[Tuple[int, int]]:
    """
    Формирует пары (СП, С) на указанную дату по схеме циклического сдвига:
      — выделяем СП (ранг=1) и С (ранг=2) из дневных участников,
      — применяем сдвиг offset = floor((on_date - epoch)/period_days),
      — для каждого СП выбираем С по кругу.
    Возвращает [(sp_uid, s_uid), ...] или [].
    """
    cfg = _get_rank_rotation_cfg(group_key)
    if not cfg:
        return []
    epoch, period_days = cfg
    off = _pair_offset(on_date, epoch, period_days)

    seniors: List[int] = []
    specs: List[int] = []
    for uid in sorted(set(int(x) for x in uids)):
        r_eff = _get_user_rank_effective(group_key, uid, on_date)
        r = r_eff if r_eff in (1, 2, 3) else _safe_rank(group_key, uid)
        if r == 1:
            seniors.append(uid)
        elif r == 2:
            specs.append(uid)

    if not seniors or not specs:
        return []

    pairs: List[Tuple[int, int]] = []
    n = len(specs)
    for i, sp in enumerate(sorted(seniors)):
        s = specs[(i + off) % n]
        pairs.append((sp, s))
    return pairs

def _pairs_indexed_for_subset(group_key: str, on_date: date, uids: List[int]) -> List[Tuple[int, int, int]]:
    """
    Возвращает пары для подмножества uids (дневные ИЛИ ночные) с их индексом:
      [(leader_uid, specialist_uid, idx), ...]
    где idx — порядковый индекс пары в текущем сдвиге (0 → «Пара #1»/🔷, 1 → «Пара #2»/🔶).
    """
    if not uids:
        return []
    cfg = _get_rank_rotation_cfg(group_key)
    if not cfg:
        return []
    epoch, period_days = cfg
    off = _pair_offset(on_date, epoch, period_days)

    seniors: List[int] = []
    specs: List[int] = []
    for uid in sorted(set(int(x) for x in uids)):
        r_eff = _get_user_rank_effective(group_key, uid, on_date)
        r = r_eff if r_eff in (1, 2, 3) else _safe_rank(group_key, uid)
        if r == 1:
            seniors.append(uid)
        elif r == 2:
            specs.append(uid)

    if not seniors or not specs:
        return []

    out: List[Tuple[int, int, int]] = []
    n = len(specs)
    for i, sp in enumerate(sorted(seniors)):
        s = specs[(i + off) % n]
        out.append((sp, s, i))
    return out


def _office_days_count_many(group_key: str, user_ids: List[int], until_date: Optional[date]) -> Dict[int, int]:
    """
    Пакетно считает офис-дни по списку user_ids до даты включительно.
    Ускоряет выбор пары «по минимальной сумме офис-дней».
    """
    if not user_ids:
        return {}
    conn = db_connection.get_connection()
    out: Dict[int, int] = {int(u): 0 for u in user_ids}
    try:
        with conn.cursor() as cur:
            if until_date:
                cur.execute("""
                    SELECT user_id, COUNT(*) AS cnt
                    FROM location_assignments
                    WHERE group_key=%s
                      AND location='office'
                      AND on_date <= %s
                      AND user_id = ANY(%s)
                    GROUP BY user_id
                """, (group_key, until_date, list(user_ids)))
            else:
                cur.execute("""
                    SELECT user_id, COUNT(*) AS cnt
                    FROM location_assignments
                    WHERE group_key=%s
                      AND location='office'
                      AND user_id = ANY(%s)
                    GROUP BY user_id
                """, (group_key, list(user_ids)))
            for uid, cnt in cur.fetchall() or []:
                out[int(uid)] = int(cnt or 0)
    except Exception:
        # в крайнем случае пусть будут нули — алгоритм отработает
        pass
    return out

def _get_base_pos(m: dict) -> int:
    """Извлекает базовую позицию участника из различных возможных ключей"""
    for k in ("base_pos", "pos", "position", "slot_pos"):
        v = m.get(k)
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return 0

def is_holiday_or_weekend(d: date) -> bool:
    """Проверяет, является ли дата праздником или выходным днем"""
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT is_holiday FROM ru_is_holiday WHERE dt = %s", (d,))
        row = cur.fetchone()
        if row is not None:
            return bool(row[0])
    # fallback: суббота/воскресенье
    return d.weekday() >= 5

def _parse_hhmm(s: str) -> time:
    """Парсит строку времени формата HH:MM в объект time"""
    hh, mm = s.split(":")
    return time(int(hh), int(mm))

def _is_night_slot(start_hhmm: str, end_hhmm: str) -> bool:
    """
    Ночь = интервал, который пересекает 00:00 (например, 20:00–08:00 или 20:00–04:00).
    """
    s = _parse_hhmm(start_hhmm)
    e = _parse_hhmm(end_hhmm)
    return (datetime.combine(date.today(), e) <= datetime.combine(date.today(), s))

def _get_user_rank_effective(group_key: str, user_id: int, on_date: date) -> Optional[int]:
    """Ранг 1..3 с учётом ротации; фоллбэк — rank из конфигурации группы."""
    try:
        from database.rank_repository import get_member_rank_effective as _eff
        r = _eff(str(group_key), int(user_id), on_date)
        if r in (1,2,3): return int(r)
    except Exception:
        pass
    try:
        info = time_repo.get_group_info(str(group_key)) or {}
        for m in info.get("members", []) or []:
            if int(m.get("user_id")) == int(user_id):
                rr = m.get("rank")
                try:
                    rr = int(rr)
                    if rr in (1,2,3): return rr
                except Exception:
                    return None
    except Exception:
        pass
    return None


def get_on_duty_members(group_key: str, on_date: date) -> List[Dict]:
    """
    Возвращает список участников группы с их рассчитанным слотом на on_date.
    Формат элемента:
      {"user_id": int, "slot_pos": int, "slot": {"pos": int, "start": "HH:MM", "end": "HH:MM", "name": "..." }}
    Игнорирует участников, у кого отдых/нет слота в этот день.
    """
    info = time_repo.get_group_info(group_key)
    if not info:
        return []
    slots = info.get("slots", [])
    members = info.get("members", [])

    from logic.duty import resolve_slot_ddnn_alternating as resolve4
    from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

    results: List[Dict] = []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)

    for m in members:
        user_id = int(m.get("user_id"))
        base_pos = _get_base_pos(m)
        slot_idx = resolve8(epoch, 8, base_pos, on_date) if period == 8 else resolve4(epoch, 4, base_pos, on_date)
        if slot_idx is None:
            continue
        slot = next((s for s in slots if s["pos"] == slot_idx), None)
        if not slot:
            continue
        results.append({"user_id": user_id, "slot_pos": slot_idx, "slot": slot})
    return results

def get_office_days_count(group_key: str, user_id: int, until_date: Optional[date] = None) -> int:
    """
    Считает общее число визитов в офис (можно расширить окном за период).
    """
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        if until_date:
            cur.execute("""
                SELECT COUNT(*) FROM location_assignments
                WHERE group_key=%s AND user_id=%s AND location='office' AND on_date <= %s
            """, (group_key, user_id, until_date))
        else:
            cur.execute("""
                SELECT COUNT(*) FROM location_assignments
                WHERE group_key=%s AND user_id=%s AND location='office'
            """, (group_key, user_id))
        return int(cur.fetchone()[0] or 0)

def _pick_one_by_min_office_days(group_key: str, user_ids: List[int], on_date: date, last_user_id: Optional[int]) -> Optional[int]:
    """
    Выбираем ОДНОГО пользоватeля среди user_ids:
      - у кого МЕНЬШЕ всего офис-дней до on_date включительно
      - при равенстве — RR-тайбрейк внутри минимума (после last_user_id)
    """
    if not user_ids:
        return None
    stats = [(uid, get_office_days_count(group_key, uid, on_date)) for uid in user_ids]
    min_cnt = min(cnt for _, cnt in stats)
    pool = sorted([uid for uid, cnt in stats if cnt == min_cnt])
    if not pool:
        return None
    if last_user_id is None or last_user_id not in pool:
        return pool[0]
    i = pool.index(last_user_id)
    return pool[(i + 1) % len(pool)]

def _cursor_get(group_key: str) -> Optional[int]:
    """Получает последнего назначенного пользователя из курсора round-robin"""
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT last_user_id FROM location_rr_cursor WHERE group_key=%s", (group_key,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

def _cursor_set(group_key: str, last_user_id: Optional[int]) -> None:
    """Сохраняет последнего назначенного пользователя в курсор round-robin"""
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO location_rr_cursor (group_key, last_user_id)
            VALUES (%s, %s)
            ON CONFLICT (group_key) DO UPDATE SET last_user_id=EXCLUDED.last_user_id
        """, (group_key, last_user_id))
        conn.commit()


def _get_user_rank(group_key: str, user_id: int) -> Optional[int]:
    """
    Возвращает ранг пользователя в группе (1=leader, 2=specialist, 3=junior),
    используя существующую логику рангов из duty_admin_repository.get_member_rank.
    Фоллбэк: пытаемся прочитать rank из time_repo.get_group_info(...).members.
    """
    # Пытаемся получить ранг из duty_admin_repository (как это делает duty_repository)
    try:
        from database.rank_repository import get_member_rank as _rank_lookup
        r = _rank_lookup(str(group_key), int(user_id))
        if r in (1, 2, 3):
            return int(r)
    except Exception:
        pass

    # Фоллбэк: смотрим конфиг группы
    try:
        info = time_repo.get_group_info(str(group_key)) or {}
        for m in info.get("members", []) or []:
            if int(m.get("user_id")) == int(user_id):
                rr = m.get("rank")
                try:
                    rr = int(rr)
                    if rr in (1, 2, 3):
                        return rr
                except Exception:
                    return None
    except Exception:
        pass

    return None


def assign_locations_for_group(group_key: str, on_date: date) -> int:
    """
    Будни:
      1 День  → вся «Пара #1» (🔷) в офис
      2 День  → вся «Пара #2» (🔶) в офис
      1 Ночь → один из «Пары #1» (🔷) с МИН. офис-дней
      2 Ночь → один из «Пары #2» (🔶) с МИН. офис-дней
    Праздник/выходной:
      День   → один из соответствующей дневной пары (МИН. офис-дней)
      Ночь  → один из соответствующей ночной пары (МИН. офис-дней)
    Фолбэк, если пары нет: минимальные офис-дни среди доступных.
    """
    members = get_on_duty_members(group_key, on_date)
    if not members:
        return 0

    # Разбивка на день/ночь
    night_flags = {m["user_id"]: _is_night_slot(m["slot"]["start"], m["slot"]["end"]) for m in members}
    day_users   = [int(m["user_id"]) for m in members if not night_flags[m["user_id"]]]
    night_users = [int(m["user_id"]) for m in members if night_flags[m["user_id"]]]

    # --- определяем slot_pos по большинству; при паритете смотрим имя слота («1 День/2 День», «1 Ночь/2 Ночь») ---
    from collections import Counter
    slot_pos_day = None
    slot_pos_night = None
    try:
        pos_day_counter = Counter()
        pos_night_counter = Counter()
        name_day_counter = Counter()    # 1/2 только для «* День»
        name_night_counter = Counter()  # 1/2 только для «* Ночь»

        for m in members:
            uid = int(m["user_id"])
            pos = int(m.get("slot", {}).get("pos") or m.get("slot_pos") or 0)
            name = str(m.get("slot", {}).get("name") or "").strip()

            if uid in day_users:
                if pos in (1, 2): pos_day_counter[pos] += 1
                if "День" in name:
                    if name.startswith("1"): name_day_counter[1] += 1
                    elif name.startswith("2"): name_day_counter[2] += 1

            if uid in night_users:
                if pos in (1, 2): pos_night_counter[pos] += 1
                if "Ночь" in name:
                    if name.startswith("1"): name_night_counter[1] += 1
                    elif name.startswith("2"): name_night_counter[2] += 1

        def _choose_pos(num_ctr: Counter, name_ctr: Counter) -> int | None:
            # сперва пытаемся по названиям слотов
            if name_ctr:
                if name_ctr.get(1, 0) > name_ctr.get(2, 0): return 1
                if name_ctr.get(2, 0) > name_ctr.get(1, 0): return 2
                if name_ctr.get(1, 0) == name_ctr.get(2, 0) and name_ctr.get(1, 0) > 0:
                    return 2  # паритет по названиям → считаем активной «2»
            # затем — по числу pos
            if num_ctr:
                if num_ctr.get(1, 0) > num_ctr.get(2, 0): return 1
                if num_ctr.get(2, 0) > num_ctr.get(1, 0): return 2
                if num_ctr.get(1, 0) == num_ctr.get(2, 0) and num_ctr.get(1, 0) > 0:
                    return 2  # паритет по pos → считаем активной «2»
            return None

        slot_pos_day = _choose_pos(pos_day_counter, name_day_counter)
        slot_pos_night = _choose_pos(pos_night_counter, name_night_counter)
    except Exception:
        pass

    is_hol = is_holiday_or_weekend(on_date)

    # Пары с индексами
    day_pairs   = _pairs_indexed_for_subset(group_key, on_date, day_users)
    night_pairs = _pairs_indexed_for_subset(group_key, on_date, night_users)

    def _pair_uids_by_idx(pairs: List[Tuple[int,int,int]], want_idx: int) -> Optional[Tuple[int,int]]:
        for a, b, idx in pairs:
            if idx == want_idx:
                return (a, b)
        return None

    conn = db_connection.get_connection()
    total_written = 0
    with conn.cursor() as cur:
        # Очистка на дату/группу
        cur.execute("DELETE FROM location_assignments WHERE group_key=%s AND on_date=%s", (group_key, on_date))

        # ---------- ДЕНЬ ----------
        if day_users:
            if not is_hol:
                # Будний день: вся пара по pos (1→idx=0, 2→idx=1)
                want_idx = 0 if slot_pos_day == 1 else 1 if slot_pos_day == 2 else 0
                office_set: Set[int] = set()
                pair = _pair_uids_by_idx(day_pairs, want_idx)
                if pair:
                    office_set = set(pair)
                else:
                    # фолбэк: лучшая пара по минимальной сумме офис-дней
                    pairs = _current_pairs_for_day(group_key, on_date, day_users)
                    if pairs:
                        stats = _office_days_count_many(group_key, list({u for p in pairs for u in p}), on_date)
                        best_pair = sorted(
                            pairs,
                            key=lambda p: (int(stats.get(int(p[0]), 0)) + int(stats.get(int(p[1]), 0)),
                                           min(int(p[0]), int(p[1])), max(int(p[0]), int(p[1])))
                        )[0]
                        office_set = set(best_pair)
                    else:
                        stats = _office_days_count_many(group_key, day_users, on_date)
                        office_set = set([u for u, _ in sorted(
                            [(u, stats.get(u, 0)) for u in day_users],
                            key=lambda t: (t[1], t[0])
                        )[:2]])
                # запись
                for uid in day_users:
                    loc = 'office' if uid in office_set else 'home'
                    cur.execute("""
                        INSERT INTO location_assignments (group_key, on_date, user_id, location)
                        VALUES (%s,%s,%s,%s)
                        ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
                    """, (group_key, on_date, uid, loc))
                    total_written += 1
                # лог пары, если ровно двое и это пара
                if len(office_set) == 2:
                    try:
                        from database.pair_repository import log_pair_day
                        a, b = tuple(sorted(list(office_set)))
                        _ = log_pair_day(group_key, on_date, a, b)
                    except Exception:
                        pass
            else:
                # Выходной/праздник: один из соответствующей дневной пары
                last_uid = _cursor_get(group_key)
                want_idx = 0 if slot_pos_day == 1 else 1 if slot_pos_day == 2 else 0
                pair = _pair_uids_by_idx(day_pairs, want_idx)
                cand = list(pair) if pair else day_users
                pick = _pick_one_by_min_office_days(group_key, cand, on_date, last_uid)
                for uid in day_users:
                    loc = 'office' if uid == pick else 'home'
                    cur.execute("""
                        INSERT INTO location_assignments (group_key, on_date, user_id, location)
                        VALUES (%s,%s,%s,%s)
                        ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
                    """, (group_key, on_date, uid, loc))
                    total_written += 1
                if pick is not None:
                    _cursor_set(group_key, pick)

        # ---------- НОЧЬ ----------
        if night_users:
            last_uid = _cursor_get(group_key)
            want_idx = 0 if slot_pos_night == 1 else 1 if slot_pos_night == 2 else 0
            pair = _pair_uids_by_idx(night_pairs, want_idx)
            cand = list(pair) if pair else night_users
            pick_n = _pick_one_by_min_office_days(group_key, cand, on_date, last_uid)
            for uid in night_users:
                loc = 'office' if uid == pick_n else 'home'
                cur.execute("""
                    INSERT INTO location_assignments (group_key, on_date, user_id, location)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
                """, (group_key, on_date, uid, loc))
                total_written += 1
            if pick_n is not None:
                _cursor_set(group_key, pick_n)

        conn.commit()
    return total_written

def assign_locations_for_group_filtered(group_key: str, on_date: date, exclude_user_ids: Optional[List[int]] = None) -> int:
    """
    То же, что assign_locations_for_group, но с исключением user_ids.
    Привязка: 🔷 → 1 День/1 Ночь (idx=0), 🔶 → 2 День/2 Ночь (idx=1). Ночью всегда один.
    """
    exclude: Set[int] = set(int(u) for u in (exclude_user_ids or []))
    members = get_on_duty_members(group_key, on_date)
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM location_assignments WHERE group_key=%s AND on_date=%s", (group_key, on_date))
        conn.commit()

    if not members:
        return 0

    members = [m for m in members if int(m.get("user_id")) not in exclude]
    if not members:
        return 0

    night_flags = {m["user_id"]: _is_night_slot(m["slot"]["start"], m["slot"]["end"]) for m in members}
    day_users   = [int(m["user_id"]) for m in members if not night_flags[m["user_id"]]]
    night_users = [int(m["user_id"]) for m in members if night_flags[m["user_id"]]]

    # --- определяем slot_pos по большинству; при паритете — по имени слота, с тай-брейком в пользу «2» ---
    from collections import Counter
    slot_pos_day = None
    slot_pos_night = None
    try:
        pos_day_counter = Counter()
        pos_night_counter = Counter()
        name_day_counter = Counter()
        name_night_counter = Counter()

        for m in members:
            uid = int(m["user_id"])
            pos = int(m.get("slot", {}).get("pos") or m.get("slot_pos") or 0)
            name = str(m.get("slot", {}).get("name") or "").strip()

            if uid in day_users:
                if pos in (1, 2): pos_day_counter[pos] += 1
                if "День" in name:
                    if name.startswith("1"): name_day_counter[1] += 1
                    elif name.startswith("2"): name_day_counter[2] += 1

            if uid in night_users:
                if pos in (1, 2): pos_night_counter[pos] += 1
                if "Ночь" in name:
                    if name.startswith("1"): name_night_counter[1] += 1
                    elif name.startswith("2"): name_night_counter[2] += 1

        def _choose_pos(num_ctr: Counter, name_ctr: Counter) -> int | None:
            if name_ctr:
                if name_ctr.get(1, 0) > name_ctr.get(2, 0): return 1
                if name_ctr.get(2, 0) > name_ctr.get(1, 0): return 2
                if name_ctr.get(1, 0) == name_ctr.get(2, 0) and name_ctr.get(1, 0) > 0:
                    return 2
            if num_ctr:
                if num_ctr.get(1, 0) > num_ctr.get(2, 0): return 1
                if num_ctr.get(2, 0) > num_ctr.get(1, 0): return 2
                if num_ctr.get(1, 0) == num_ctr.get(2, 0) and num_ctr.get(1, 0) > 0:
                    return 2
            return None

        slot_pos_day = _choose_pos(pos_day_counter, name_day_counter)
        slot_pos_night = _choose_pos(pos_night_counter, name_night_counter)
    except Exception:
        pass

    is_hol = is_holiday_or_weekend(on_date)

    day_pairs   = _pairs_indexed_for_subset(group_key, on_date, day_users)
    night_pairs = _pairs_indexed_for_subset(group_key, on_date, night_users)

    def _pair_uids_by_idx(pairs: List[Tuple[int,int,int]], want_idx: int) -> Optional[Tuple[int,int]]:
        for a, b, idx in pairs:
            if idx == want_idx:
                return (a, b)
        return None

    total_written = 0
    with conn.cursor() as cur:
        # ------ ДЕНЬ ------
        if day_users:
            if not is_hol:
                want_idx = 0 if slot_pos_day == 1 else 1 if slot_pos_day == 2 else 0
                office_set: Set[int] = set()
                pair = _pair_uids_by_idx(day_pairs, want_idx)
                if pair:
                    office_set = set(pair)
                else:
                    pairs = _current_pairs_for_day(group_key, on_date, day_users)
                    if pairs:
                        stats = _office_days_count_many(group_key, list({u for p in pairs for u in p}), on_date)
                        best_pair = sorted(
                            pairs,
                            key=lambda p: (int(stats.get(int(p[0]), 0)) + int(stats.get(int(p[1]), 0)),
                                           min(int(p[0]), int(p[1])), max(int(p[0]), int(p[1])))
                        )[0]
                        office_set = set(best_pair)
                    else:
                        stats = _office_days_count_many(group_key, day_users, on_date)
                        office_set = set([u for u, _ in sorted(
                            [(u, stats.get(u, 0)) for u in day_users],
                            key=lambda t: (t[1], t[0])
                        )[:2]])
                for uid in day_users:
                    loc = 'office' if uid in office_set else 'home'
                    cur.execute("""
                        INSERT INTO location_assignments (group_key, on_date, user_id, location)
                        VALUES (%s,%s,%s,%s)
                        ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
                    """, (group_key, on_date, uid, loc))
                    total_written += 1
                if len(office_set) == 2:
                    try:
                        from database.pair_repository import log_pair_day
                        a, b = tuple(sorted(list(office_set)))
                        _ = log_pair_day(group_key, on_date, a, b)
                    except Exception:
                        pass
            else:
                last_uid = _cursor_get(group_key)
                want_idx = 0 if slot_pos_day == 1 else 1 if slot_pos_day == 2 else 0
                pair = _pair_uids_by_idx(day_pairs, want_idx)
                cand = list(pair) if pair else day_users
                pick = _pick_one_by_min_office_days(group_key, cand, on_date, last_uid)
                for uid in day_users:
                    loc = 'office' if uid == pick else 'home'
                    cur.execute("""
                        INSERT INTO location_assignments (group_key, on_date, user_id, location)
                        VALUES (%s,%s,%s,%s)
                        ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
                    """, (group_key, on_date, uid, loc))
                    total_written += 1
                if pick is not None:
                    _cursor_set(group_key, pick)

        # ------ НОЧЬ ------
        if night_users:
            last_uid = _cursor_get(group_key)
            want_idx = 0 if slot_pos_night == 1 else 1 if slot_pos_night == 2 else 0
            pair = _pair_uids_by_idx(night_pairs, want_idx)
            cand = list(pair) if pair else night_users
            pick_n = _pick_one_by_min_office_days(group_key, cand, on_date, last_uid)
            for uid in night_users:
                loc = 'office' if uid == pick_n else 'home'
                cur.execute("""
                    INSERT INTO location_assignments (group_key, on_date, user_id, location)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
                """, (group_key, on_date, uid, loc))
                total_written += 1
            if pick_n is not None:
                _cursor_set(group_key, pick_n)

        conn.commit()
    return total_written

def get_locations(on_date: date, group_key: Optional[str] = None) -> List[Dict]:
    """Возвращает назначения локаций на указанную дату.
       Пытается обогатить результат ФИО/username из таблицы users (если есть).
       Поля в выдаче: group_key, on_date, user_id, location, (optional) full_name, username.
    """
    conn = db_connection.get_connection()

    # Вариант №1 — с JOIN users (предпочтительный)
    try:
        with conn.cursor() as cur:
            if group_key:
                cur.execute("""
                    SELECT la.group_key,
                           la.on_date,
                           la.user_id,
                           la.location,
                           COALESCE(
                               NULLIF(TRIM(CONCAT(COALESCE(u.first_name,''),' ',COALESCE(u.last_name,''))), ''),
                               u.full_name, u.name
                           ) AS full_name,
                           u.username
                    FROM location_assignments la
                    LEFT JOIN users u ON u.user_id = la.user_id
                    WHERE la.on_date=%s AND la.group_key=%s
                    ORDER BY la.group_key, la.user_id
                """, (on_date, group_key))
            else:
                cur.execute("""
                    SELECT la.group_key,
                           la.on_date,
                           la.user_id,
                           la.location,
                           COALESCE(
                               NULLIF(TRIM(CONCAT(COALESCE(u.first_name,''),' ',COALESCE(u.last_name,''))), ''),
                               u.full_name, u.name
                           ) AS full_name,
                           u.username
                    FROM location_assignments la
                    LEFT JOIN users u ON u.user_id = la.user_id
                    WHERE la.on_date=%s
                    ORDER BY la.group_key, la.user_id
                """, (on_date,))
            rows = cur.fetchall() or []
        out: List[Dict] = []
        for r in rows:
            out.append({
                "group_key": r[0],
                "on_date":   r[1],
                "user_id":   r[2],
                "location":  r[3],
                "full_name": r[4],
                "username":  r[5],
            })
        return out
    except Exception:
        # Если таблицы users нет или другая ошибка SQL — откатываем и используем простой вариант без JOIN
        try:
            conn.rollback()
        except Exception:
            pass

    # Вариант №2 — без JOIN (базовый)
    with conn.cursor() as cur:
        if group_key:
            cur.execute("""
                SELECT group_key, on_date, user_id, location
                FROM location_assignments
                WHERE on_date=%s AND group_key=%s
                ORDER BY group_key, user_id
            """, (on_date, group_key))
        else:
            cur.execute("""
                SELECT group_key, on_date, user_id, location
                FROM location_assignments
                WHERE on_date=%s
                ORDER BY group_key, user_id
            """, (on_date,))
        rows = cur.fetchall() or []
    return [{"group_key": r[0], "on_date": r[1], "user_id": r[2], "location": r[3]} for r in rows]

def office_report(group_key: str, date_from: date, date_to: date) -> List[Dict]:
    """
    Свод по офис-дням за период по группе.
    """
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT user_id, COUNT(*) AS office_days
            FROM location_assignments
            WHERE group_key=%s AND on_date BETWEEN %s AND %s AND location='office'
            GROUP BY user_id
            ORDER BY office_days DESC, user_id
        """, (group_key, date_from, date_to))
        rows = cur.fetchall() or []
    return [{"user_id": r[0], "office_days": int(r[1])} for r in rows]

# ===================== РУЧНЫЕ/СЕРВИСНЫЕ АПИ (для хендлеров) =====================

def upsert_manual(group_key: str, on_date: date, user_id: int, location: str, phase_kind: Optional[str] = None) -> bool:
    """
    Ручная запись/перезапись назначения для пользователя на дату.
    phase_kind ('day'/'night') у нас в таблице не хранится — параметр игнорируется,
    оставлен для совместимости/логики на уровне хендлеров.
    """
    loc = "office" if str(location).lower() in ("office", "офис", "🏢") else "home"
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO location_assignments (group_key, on_date, user_id, location)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
        """, (str(group_key), on_date, int(user_id), loc))
        conn.commit()
    return True

# Алиасы для совместимости с вызовами из разных версий хендлеров
def upsert_assignment(group_key: str, on_date: date, user_id: int, location: str, phase_kind: Optional[str] = None) -> bool:
    return upsert_manual(group_key, on_date, user_id, location, phase_kind)

def assign_manual(group_key: str, on_date: date, user_id: int, location: str, phase_kind: Optional[str] = None) -> bool:
    return upsert_manual(group_key, on_date, user_id, location, phase_kind)

def assign_locations_range(group_key: str, start_date: date, days: int) -> int:
    """
    Массовое авто-назначение на диапазон дней начиная с start_date включительно.
    Возвращает общее число записанных строк (включая home/office).
    """
    total = 0
    d = start_date
    for _ in range(max(0, int(days))):
        total += int(assign_locations_for_group(group_key, d) or 0)
        d += timedelta(days=1)
    return total

# алиас для совместимости
def assign(group_key: str, start_date: date, days: int) -> int:
    return assign_locations_range(group_key, start_date, days)

def clear_future(group_key: str) -> int:
    """
    Удаляет ВСЕ будущие назначения для группы (on_date > CURRENT_DATE).
    Возвращает число удалённых строк.
    """
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM location_assignments WHERE group_key=%s AND on_date > CURRENT_DATE", (str(group_key),))
        deleted = cur.rowcount or 0
        conn.commit()
    return int(deleted)

# алиас для совместимости
def clear_future_for_group(group_key: str) -> int:
    return clear_future(group_key)



def get_location_map_for_users_on(day_, user_ids):
    ids = list({int(x) for x in user_ids})
    if not ids:
        return {}
    conn = db_connection.get_connection()            # ← вот так
    with conn.cursor() as cur:
        cur.execute(
            """
            select user_id,
                   case when is_office then 'office' else 'home' end as loc
            from custom_schedule_shifts
            where (shift_date = %s::date or work_date = %s::date)
              and user_id = ANY(%s)
            """,
            (day_, day_, ids)
        )
        rows = cur.fetchall()
    return {int(uid): (loc or 'home') for uid, loc in rows}


def get_group_locations_today(group_key: str, cutoff_hour: int = 6):
    """
    Возвращает локации на 'сегодня' по группе.
    Если сейчас раннее утро (до cutoff_hour) и записей на сегодня нет,
    подхватывает записи за вчера – чтобы ночные/перекрывающиеся смены не выпадали.
    """
    now = datetime.now(MSK)
    today = now.date()

    sql_today = """
        SELECT css.user_id,
               COALESCE(u.username, '') AS username,
               css.location,
               css.is_office
        FROM custom_schedule_shifts css
        LEFT JOIN users u ON u.user_id = css.user_id
        WHERE css.group_key = %s
          AND (css.shift_date = %s::date OR css.work_date = %s::date)
        ORDER BY css.user_id
    """

    sql_yesterday = """
        SELECT css.user_id,
               COALESCE(u.username, '') AS username,
               css.location,
               css.is_office
        FROM custom_schedule_shifts css
        LEFT JOIN users u ON u.user_id = css.user_id
        WHERE css.group_key = %s
          AND (css.shift_date = (%s::date - INTERVAL '1 day')
               OR css.work_date = (%s::date - INTERVAL '1 day'))
        ORDER BY css.user_id
    """

    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        # 1) Пытаемся взять 'сегодня'
        cur.execute(sql_today, (group_key, today, today))
        rows = cur.fetchall()

        # 2) Если пусто и раннее утро — fallback на 'вчера'
        if not rows and now.hour < cutoff_hour:
            cur.execute(sql_yesterday, (group_key, today, today))
            rows = cur.fetchall()

    return [(int(uid), str(username), str(loc), bool(is_office)) for uid, username, loc, is_office in rows]


