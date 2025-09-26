# /home/telegrambot/shift_tracker_bot/database/location_repository.py
# -*- coding: utf-8 -*-
from datetime import date, time, datetime, timedelta
from typing import List, Dict, Optional, Tuple
from database.connection import db_connection
from database import time_repository as time_repo

def is_holiday_or_weekend(d: date) -> bool:
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT is_holiday FROM ru_is_holiday WHERE dt = %s", (d,))
        row = cur.fetchone()
        if row is not None:
            return bool(row[0])
    # fallback: суббота/воскресенье
    return d.weekday() >= 5

def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))

def _is_night_slot(start_hhmm: str, end_hhmm: str) -> bool:
    """
    Ночь = интервал, который пересекает 00:00 (например, 20:00–08:00 или 20:00–04:00).
    """
    s = _parse_hhmm(start_hhmm)
    e = _parse_hhmm(end_hhmm)
    return (datetime.combine(date.today(), e) <= datetime.combine(date.today(), s))

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
        base_pos = int(m.get("base_pos") or 0)
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

def _pick_one_by_max_office_days(group_key: str, user_ids: List[int], on_date: date, last_user_id: Optional[int]) -> Optional[int]:
    """
    Выбираем одного пользователя среди user_ids:
      - у кого БОЛЬШЕ всего офис-дней (требование пользователя)
      - при равенстве — round-robin тай-брейк (после last_user_id)
    """
    if not user_ids:
        return None
    # посчитаем историю
    stats = [(uid, get_office_days_count(group_key, uid, on_date)) for uid in user_ids]
    max_cnt = max(cnt for _, cnt in stats)
    pool = [uid for uid, cnt in stats if cnt == max_cnt]
    pool_sorted = sorted(pool)  # стабильный порядок

    if last_user_id is None or last_user_id not in pool_sorted:
        return pool_sorted[0]
    # RR внутри пула
    idx = pool_sorted.index(last_user_id)
    return pool_sorted[(idx + 1) % len(pool_sorted)]

def _cursor_get(group_key: str) -> Optional[int]:
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT last_user_id FROM location_rr_cursor WHERE group_key=%s", (group_key,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

def _cursor_set(group_key: str, last_user_id: Optional[int]) -> None:
    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO location_rr_cursor (group_key, last_user_id)
            VALUES (%s, %s)
            ON CONFLICT (group_key) DO UPDATE SET last_user_id=EXCLUDED.last_user_id
        """, (group_key, last_user_id))
        conn.commit()

def assign_locations_for_group(group_key: str, on_date: date) -> int:
    """
    Главная функция распределения локаций по группе на дату on_date.
    Правила:
      - будни & НЕ ночной слот → все 'office'
      - выходной/праздник ИЛИ ночной слот → ровно один 'office' (остальные 'home'),
        выбранный у кого БОЛЬШЕ всего офис-дней (при равенстве — RR тай-брейк).
    Возвращает количество записанных назначений.
    """
    members = get_on_duty_members(group_key, on_date)
    if not members:
        return 0

    is_hol = is_holiday_or_weekend(on_date)
    # узнаем, какие слоты ночные
    night_flags = {m["user_id"]: _is_night_slot(m["slot"]["start"], m["slot"]["end"]) for m in members}

    # делим на дневных и ночных на эту дату
    day_users = [m["user_id"] for m in members if not night_flags[m["user_id"]]]
    night_users = [m["user_id"] for m in members if night_flags[m["user_id"]]]

    total_written = 0
    conn = db_connection.get_connection()
    with conn.cursor() as cur:

        def _upsert(uid: int, loc: str):
            cur.execute("""
                INSERT INTO location_assignments (group_key, on_date, user_id, location, slot_pos)
                VALUES (%s,%s,%s,%s,
                        (SELECT slot_pos FROM (
                            VALUES %s
                        ) AS v(uid, slot_pos) WHERE uid=%s))
                ON CONFLICT (group_key, on_date, user_id)
                DO UPDATE SET location=EXCLUDED.location
            """,
            # маленький хак: вместо VALUES %s можно просто передавать None и потом отдельным апдейтом slot_pos,
            # чтобы не усложнять. Оставим проще:
            )

        # Проще: сначала очистим на дату для группы, затем вставим заново
        cur.execute("DELETE FROM location_assignments WHERE group_key=%s AND on_date=%s", (group_key, on_date))

        # ДЕНЬ
        if day_users:
            if not is_hol:
                # будний день: все в офис
                for uid in day_users:
                    cur.execute("""
                        INSERT INTO location_assignments (group_key, on_date, user_id, location)
                        VALUES (%s,%s,%s,'office')
                        ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location='office'
                    """, (group_key, on_date, uid))
                    total_written += 1
            else:
                # выходной/праздник: один в офис, остальные домой
                last_uid = _cursor_get(group_key)
                pick = _pick_one_by_max_office_days(group_key, day_users, on_date, last_uid)
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

        # НОЧЬ — всегда только один в офис
        if night_users:
            last_uid = _cursor_get(group_key)
            pick = _pick_one_by_max_office_days(group_key, night_users, on_date, last_uid)
            for uid in night_users:
                loc = 'office' if uid == pick else 'home'
                cur.execute("""
                    INSERT INTO location_assignments (group_key, on_date, user_id, location)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (group_key, on_date, user_id) DO UPDATE SET location=EXCLUDED.location
                """, (group_key, on_date, uid, loc))
                total_written += 1
            if pick is not None:
                _cursor_set(group_key, pick)

        conn.commit()
    return total_written

def get_locations(on_date: date, group_key: Optional[str] = None) -> List[Dict]:
    conn = db_connection.get_connection()
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
