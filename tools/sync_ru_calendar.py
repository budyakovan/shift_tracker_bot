# /home/telegrambot/shift_tracker_bot/tools/sync_ru_calendar.py
from __future__ import annotations

import os
import time
from datetime import date, timedelta, datetime
from typing import Iterable, Optional

import requests
import psycopg2
import psycopg2.extras


PG_DSN = (
    os.getenv("PG_DSN")
    or os.getenv("DATABASE_URL")  # если вдруг используется такой env
    or "dbname=shift_tracker_db user=shift_tracker_bot host=127.0.0.1"
)
COUNTRY = "ru"


def _connect():
    return psycopg2.connect(PG_DSN)


def fetch_year(year: int) -> str:
    """
    Возвращает строку из 365/366 символов (0/1/2/4) для года.
    0,2,4 — рабочие; 1 — выходной/праздник.
    Документация: https://isdayoff.ru/#api-advanced
    """
    url = f"https://isdayoff.ru/api/getdata?year={year}&cc={COUNTRY}&pre=1"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.text.strip()


def code_to_is_working(ch: str) -> bool:
    # 0=рабочий, 1=выходной/праздник, 2=сокращённый (рабочий), 4=рабочий
    return ch in ("0", "2", "4")


def upsert_year(cur, year: int, series: str) -> int:
    """
    UPSERT в ru_calendar на весь год. Возвращает кол-во обработанных дней.
    """
    d = date(year, 1, 1)
    for i, ch in enumerate(series):
        cur.execute(
            """
            INSERT INTO ru_calendar (dt, is_working, source, updated_at)
            VALUES (%s, %s, 'isdayoff', now())
            ON CONFLICT (dt) DO UPDATE
               SET is_working = EXCLUDED.is_working,
                   source     = EXCLUDED.source,
                   updated_at = now()
            """,
            (d + timedelta(days=i), code_to_is_working(ch)),
        )
    return len(series)


def refresh_mv(conn) -> None:
    """
    Обновляет материализованное представление.
    Пытается CONCURRENTLY, в случае ошибки — обычный REFRESH.
    """
    try:
        with conn, conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY ru_is_holiday_mv;")
    except Exception:
        conn.rollback()
        with conn, conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW ru_is_holiday_mv;")


def run_sync(years: Optional[Iterable[int]] = None) -> dict:
    """
    Основной вызов для кода бота.
    years=None → [текущий, следующий].
    Возвращает словарь-итог: годы, сколько дней обработано, длительность, рефреш MV.
    """
    if years is None:
        y = date.today().year
        years = [y, y + 1]

    years = sorted(set(int(y) for y in years))
    t0 = time.time()
    processed_days = 0
    with _connect() as conn, conn.cursor() as cur:
        for y in years:
            series = fetch_year(y)
            processed_days += upsert_year(cur, y, series)
        # после всех апдейтов — рефреш MV
        refresh_mv(conn)

    return {
        "years": years,
        "processed_days": processed_days,
        "duration_s": round(time.time() - t0, 3),
        "mv_refreshed": True,
    }


def get_status() -> dict:
    """
    Возвращает статус из ru_calendar и ru_is_holiday_mv:
    min_dt, max_dt, rows, last_update, mv_max_dt, mv_rows.
    """
    with _connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            "SELECT MIN(dt) AS min_dt, MAX(dt) AS max_dt, COUNT(*) AS rows, MAX(updated_at) AS last_update "
            "FROM ru_calendar"
        )
        row = cur.fetchone()
        min_dt = row["min_dt"]
        max_dt = row["max_dt"]
        rows = row["rows"]
        last_update = row["last_update"]

        try:
            cur.execute(
                "SELECT MIN(dt) AS mv_min_dt, MAX(dt) AS mv_max_dt, COUNT(*) AS mv_rows FROM ru_is_holiday_mv"
            )
            mv_row = cur.fetchone()
            mv_min_dt = mv_row["mv_min_dt"]
            mv_max_dt = mv_row["mv_max_dt"]
            mv_rows = mv_row["mv_rows"]
        except Exception:
            mv_min_dt = mv_max_dt = None
            mv_rows = None

    return {
        "min_dt": min_dt,
        "max_dt": max_dt,
        "rows": rows,
        "last_update": last_update,
        "mv_min_dt": mv_min_dt,
        "mv_max_dt": mv_max_dt,
        "mv_rows": mv_rows,
        "now": datetime.now(),
    }


# Опциональный CLI-запуск (для cron/systemd)
if __name__ == "__main__":
    info = run_sync()
    print(
        f"Synced years={info['years']} processed_days={info['processed_days']} "
        f"duration_s={info['duration_s']} mv_refreshed={info['mv_refreshed']}"
    )
