# /home/telegrambot/shift_tracker_bot/handlers/holiday_handlers.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Tuple, Optional
from itertools import islice

from telegram import Update
from telegram.ext import ContextTypes

from database.connection import db_connection

logger = logging.getLogger(__name__)


# ---------- low-level helpers ----------

def _rel_exists(conn, relname: str) -> bool:
    """Есть ли такая таблица/представление/матвью в public."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (relname,))
        return cur.fetchone()[0] is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """Надёжная проверка существования колонки (в т.ч. на materialized view)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public'
              AND c.relname = %s
              AND a.attname = %s
              AND a.attisdropped = FALSE
              AND a.attnum > 0
            LIMIT 1
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None


# ---------- status/meta ----------

def _holidays_status(conn) -> Tuple[str, date | None, date | None, int, datetime | None]:
    """
    Возвращает:
      (источник данных 'ru_is_holiday_mv' | 'ru_is_holiday' | 'ru_calendar',
       min(dt), max(dt), count(*),
       MAX(updated_at) из ru_calendar, если колонка есть)
    """
    if   _rel_exists(conn, "ru_is_holiday_mv"):
        src = "ru_is_holiday_mv"
    elif _rel_exists(conn, "ru_is_holiday"):
        src = "ru_is_holiday"
    elif _rel_exists(conn, "ru_calendar"):
        src = "ru_calendar"
    else:
        src = "ru_is_holiday"  # last resort

    cov_from = cov_to = None
    cnt = 0
    with conn.cursor() as cur:
        cur.execute(f"SELECT MIN(dt), MAX(dt), COUNT(*) FROM {src}")
        cov_from, cov_to, cnt = cur.fetchone()

    last_upd = None
    if _rel_exists(conn, "ru_calendar") and _column_exists(conn, "ru_calendar", "updated_at"):
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(updated_at) FROM ru_calendar")
            last_upd = cur.fetchone()[0]

    return src, cov_from, cov_to, (cnt or 0), last_upd


# ---------- period parsing ----------

def _parse_period_args(args: list[str]) -> Tuple[date, date]:
    """
    Поддерживаем форматы:
      • (нет аргументов) → текущий год
      • <YYYY>
      • <YYYY> <YYYY>
      • <YYYY-MM>  ← НОВОЕ: целый месяц
      • <YYYY-MM-DD>
      • <YYYY-MM-DD> <YYYY-MM-DD>
    Возвращаем (date_from, date_to) включительно.
    """
    today = date.today()

    def _year_bounds(y: int) -> Tuple[date, date]:
        return date(y, 1, 1), date(y, 12, 31)

    def _month_bounds(y: int, m: int) -> Tuple[date, date]:
        first = date(y, m, 1)
        if m == 12:
            last = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            last = date(y, m + 1, 1) - timedelta(days=1)
        return first, last

    if not args:
        return _year_bounds(today.year)

    if len(args) == 1:
        a = args[0]
        # YYYY
        if len(a) == 4 and a.isdigit():
            y = int(a)
            return _year_bounds(y)
        # YYYY-MM
        if len(a) == 7 and a[4] == '-' and a[:4].isdigit() and a[5:7].isdigit():
            y = int(a[:4])
            m = int(a[5:7])
            if 1 <= m <= 12:
                return _month_bounds(y, m)
            raise ValueError("Неверный месяц в формате YYYY-MM.")
        # YYYY-MM-DD
        try:
            d = date.fromisoformat(a)
            return d, d
        except Exception:
            raise ValueError("Ожидаю год (YYYY), месяц (YYYY-MM) или дату (YYYY-MM-DD).")

    a1, a2 = args[0], args[1]

    def _to_span(s: str) -> Tuple[date, date]:
        if len(s) == 4 and s.isdigit():
            y = int(s)
            return _year_bounds(y)
        if len(s) == 7 and s[4] == '-' and s[:4].isdigit() and s[5:7].isdigit():
            y = int(s[:4]); m = int(s[5:7])
            if 1 <= m <= 12:
                return _month_bounds(y, m)
            raise ValueError("Неверный месяц в формате YYYY-MM.")
        d = date.fromisoformat(s)
        return d, d

    d1_from, d1_to = _to_span(a1)
    d2_from, d2_to = _to_span(a2)
    return min(d1_from, d2_from), max(d1_to, d2_to)


# ---------- discovery for listing ----------

def _pick_text_col(conn, table: str) -> str | None:
    """Возвращает текстовую колонку для названия праздника: title → name → holiday_name."""
    for c in ("title", "name", "holiday_name"):
        if _column_exists(conn, table, c):
            return c
    return None


def _table_with_flags(conn) -> Tuple[str, str | None, str | None]:
    """
    Базовый источник дат и флагов.
    Возвращает (table, text_col_or_none, flag_kind) где:
      flag_kind ∈ {"is_holiday", "is_working", None}
    Приоритет таблиц: ru_is_holiday_mv → ru_is_holiday → ru_calendar.
    """
    candidates: list[str] = []
    if _rel_exists(conn, "ru_is_holiday_mv"):
        candidates.append("ru_is_holiday_mv")
    if _rel_exists(conn, "ru_is_holiday"):
        candidates.append("ru_is_holiday")
    if _rel_exists(conn, "ru_calendar"):
        candidates.append("ru_calendar")

    for t in candidates:
        if not _column_exists(conn, t, "dt"):
            continue
        txt = _pick_text_col(conn, t)
        if _column_exists(conn, t, "is_holiday"):
            return t, txt, "is_holiday"
        if _column_exists(conn, t, "is_working"):
            return t, txt, "is_working"
        # иначе — попробуем всё равно этот источник (флагов нет)
        return t, txt, None
    # если вообще ничего не нашли — вернём заглушку
    return (candidates[0] if candidates else "ru_is_holiday"), None, None


def _title_source(conn) -> Tuple[str | None, str | None]:
    """
    Источник текстовых названий (предпочитаем ru_calendar).
    Возвращает (table, text_col) или (None, None).
    """
    if _rel_exists(conn, "ru_calendar") and _column_exists(conn, "ru_calendar", "dt"):
        col = _pick_text_col(conn, "ru_calendar")
        if col:
            return "ru_calendar", col
    return None, None


# ---------- list & pretty formatting ----------

def _list_holidays_in_range(conn, d_from: date, d_to: date, limit: Optional[int] = 20) -> Tuple[list[tuple[date, str]], int]:
    """
    Возвращает (top_list, total_count):
      top_list: список (dt, title) длиной до limit (или все, если limit=None).
      total_count: общее количество найденных «праздничных/выходных» дней.

    Алгоритм:
      1) если есть флаг is_holiday → используем его;
      2) иначе, если есть is_working → используем NOT is_working;
      3) иначе — пробуем присоединиться к ru_calendar и взять NOT rc.is_working;
      4) иначе — считаем выходные как суббота/воскресенье.
    """
    table, txt_col, flag_kind = _table_with_flags(conn)
    title_tbl, title_col = _title_source(conn)
    top: list[tuple[date, str]] = []
    total = 0

    with conn.cursor() as cur:
        if flag_kind == "is_holiday":
            base_title = (txt_col or "''")
            join_title = (
                f"LEFT JOIN {title_tbl} t ON t.dt = p.dt"
                if (title_tbl and title_col and title_tbl != table) else ""
            )
            select_title = (
                f"COALESCE(t.{title_col}::text, {base_title}::text)"
                if (title_tbl and title_col and title_tbl != table) else f"{base_title}::text"
            )
            cur.execute(
                f"""
                SELECT p.dt, {select_title} AS title
                FROM {table} p
                {join_title}
                WHERE p.dt BETWEEN %s AND %s
                  AND p.is_holiday = TRUE
                ORDER BY p.dt
                """,
                (d_from, d_to),
            )
            rows = cur.fetchall() or []
        elif txt_col:
            cur.execute(
                f"""
                SELECT dt, {txt_col}::text
                FROM {table}
                WHERE dt BETWEEN %s AND %s
                  AND COALESCE(NULLIF({txt_col}::text, ''), '') <> ''
                ORDER BY dt
                """,
                (d_from, d_to),
            )
            rows = cur.fetchall() or []
        else:
            # надёжный фолбэк: «хотя бы выходные»
            cur.execute(
                """
                SELECT d::date AS dt, ''::text
                FROM generate_series(%s::date, %s::date, '1 day') AS d
                WHERE EXTRACT(ISODOW FROM d)::int IN (6,7)
                ORDER BY 1
                """,
                (d_from, d_to),
            )
            rows = cur.fetchall() or []

    total = len(rows)
    rows_slice = rows if limit is None else list(islice(rows, 0, limit))
    for dt_val, title in rows_slice:
        top.append((dt_val, (title or "")))
    return top, total


def _format_span(a: date, b: date) -> str:
    """Красивое форматирование интервала дат."""
    if a == b:
        return f"{a:%d.%m.%Y}"
    if a.year == b.year:
        if a.month == b.month:
            return f"{a:%d}–{b:%d.%m.%Y}"
        return f"{a:%d.%m}–{b:%d.%m.%Y}"
    return f"{a:%d.%m.%Y}–{b:%d.%m.%Y}"


def _collapse_holiday_ranges(
    rows: list[tuple[date, str]],
    limit_ranges: Optional[int] = 20
) -> tuple[list[tuple[date, date, Optional[str], int]], int]:
    """
    Схлопывает соседние даты (d[i+1] = d[i] + 1) в интервалы.
    Если у интервала у всех дней одинаковый непустой title (без учёта регистра) — используем его; иначе title=None.
    Возвращает (ограниченный список интервалов, всего интервалов).
    """
    if not rows:
        return [], 0

    ranges: list[tuple[date, date, Optional[str], int]] = []
    start = prev = rows[0][0]
    span_len = 0
    titles: list[str] = []

    def flush():
        nonlocal ranges, start, prev, span_len, titles
        if span_len == 0:
            return
        nonempty = [t for t in titles if t.strip()]
        if nonempty:
            norm = {t.strip().lower() for t in nonempty}
            title_to_show: Optional[str] = nonempty[0] if len(norm) == 1 else None
        else:
            title_to_show = None
        ranges.append((start, prev, title_to_show, span_len))

    for dt_val, title in rows:
        if span_len == 0:
            start = prev = dt_val
            span_len = 1
            titles = [title or ""]
            continue
        if (dt_val - prev).days == 1:
            prev = dt_val
            span_len += 1
            titles.append(title or "")
        else:
            flush()
            start = prev = dt_val
            span_len = 1
            titles = [title or ""]
    flush()

    total_spans = len(ranges)
    if limit_ranges is not None:
        ranges = ranges[:limit_ranges]
    return ranges, total_spans


def _year_links(d_from: date, d_to: date) -> list[tuple[int, str]]:
    """Ссылки на производственный календарь по годам (можно заменить на корпоративные)."""
    years = range(d_from.year, d_to.year + 1)
    return [(y, f"https://www.consultant.ru/law/ref/calendar/proizvodstvennye/{y}/") for y in years]


# ---------- handlers ----------

async def holidays_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /holidays_status — показать покрытие календаря и дату последнего обновления ru_calendar.
    /holidays_status <YYYY|YYYY YYYY|YYYY-MM|YYYY-MM-DD [YYYY-MM-DD]>:
        • если указан YYYY-MM — вывести список праздничных/выходных дней за месяц,
        • иначе — схлопнутые периоды за диапазон.
    """
    try:
        conn = db_connection.get_connection()
        src, cov_from, cov_to, cnt, last_upd = _holidays_status(conn)

        lines = []
        lines.append("📅 <b>Календарь праздников</b>")
        lines.append(f"Источник: <code>{src}</code>")
        if cov_from and cov_to:
            lines.append(f"Покрытие: <b>{cov_from:%Y-%m-%d}…{cov_to:%Y-%m-%d}</b> (строк: {cnt})")
        else:
            lines.append("Покрытие: нет данных")

        if last_upd:
            lines.append(f"Последняя правка <code>ru_calendar</code>: {last_upd:%Y-%m-%d %H:%M}")

        # Если задан период — месяц или иной диапазон
        args = context.args or []
        if args:
            try:
                d_from, d_to = _parse_period_args(args)
                if len(args) == 1 and len(args[0]) == 7 and args[0][4] == '-':
                    # МЕСЯЦ: выводим дни
                    all_days, total_days = _list_holidays_in_range(conn, d_from, d_to, limit=None)
                    lines.append("")
                    lines.append(f"🎉 Праздники/выходные за {d_from:%Y-%m}:")
                    if total_days > 0:
                        for dt_val, title in all_days:
                            label = title.strip() if title and title.strip() else "выходной"
                            lines.append(f"• {dt_val:%d.%m.%Y} — {label}")
                        lines.append(f"Итого: {total_days} дн.")
                    else:
                        lines.append("ℹ️ В указанном месяце праздников/выходных нет.")
                else:
                    # Прочие диапазоны: схлопнутые периоды
                    all_days, total_days = _list_holidays_in_range(conn, d_from, d_to, limit=None)
                    if total_days > 0:
                        spans, spans_total = _collapse_holiday_ranges(all_days, limit_ranges=20)
                        lines.append("")
                        lines.append(f"🎉 Праздники/выходные в диапазоне {d_from:%Y-%m-%d}…{d_to:%Y-%m-%d}:")
                        for a, b, title, days in spans:
                            label = (title.strip() if title and title.strip()
                                     else ("выходные" if (a != b or title is None) else "праздничный/выходной день"))
                            lines.append(f"• {_format_span(a, b)} — {label} ({days} дн.)")
                        if spans_total > len(spans):
                            lines.append(f"…и ещё {spans_total - len(spans)} период(а).")
                    else:
                        lines.append("")
                        lines.append("ℹ️ В указанном диапазоне праздников не найдено.")
            except Exception as _e:
                logger.exception("holidays_status period list failed: %s", _e)
                lines.append("")
                lines.append("ℹ️ Не удалось сформировать список праздничных дней (смотрите логи).")

        # Предупреждения
        warn = []
        today = date.today()
        if cov_to and (cov_to - today).days < 120:
            warn.append("Покрытие меньше чем на 120 дней вперёд.")
        if last_upd and (datetime.now(tz=last_upd.tzinfo) - last_upd).days > 90:
            warn.append("Давно не было правок в ru_calendar (возможны переносы/выходные).")
        if warn:
            lines.append("⚠️ " + "\n⚠️ ".join(warn))
            lines.append(f"Например, можно запустить: <code>/holidays_sync {today.year}</code>")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception("holidays_status failed: %s", e)
        await update.message.reply_text("⚠️ Произошла ошибка. Логи сохранены, разберёмся.")


async def holidays_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /holidays_sync
    /holidays_sync <YYYY>
    /holidays_sync <YYYY> <YYYY>
    /holidays_sync <YYYY-MM-DD> <YYYY-MM-DD>

    Сейчас: рефреш materialized view (если есть) и краткий отчёт по количеству праздничных/выходных дней.
    """
    args = context.args or []
    try:
        d_from, d_to = _parse_period_args(args)
    except ValueError as ve:
        await update.message.reply_text(f"❌ {ve}")
        return

    try:
        conn = db_connection.get_connection()
        await update.message.reply_text(
            f"⏳ Запускаю синхронизацию: {d_from:%Y-%m-%d}…{d_to:%Y-%m-%d}"
        )

        if _rel_exists(conn, "ru_is_holiday_mv"):
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY ru_is_holiday_mv;")
        else:
            logger.info("ru_is_holiday_mv не найден — пропускаем REFRESH")

        src, cov_from, cov_to, cnt, last_upd = _holidays_status(conn)
        msg = ["✅ <b>Синхронизация завершена</b>.", f"Источник: <code>{src}</code>"]
        if cov_from and cov_to:
            msg.append(f"Покрытие: <b>{cov_from:%Y-%m-%d}…{cov_to:%Y-%m-%d}</b> (строк: {cnt})")
        if last_upd:
            msg.append(f"Последняя правка <code>ru_calendar</code>: {last_upd:%Y-%m-%d %H:%M}")

        # ---- Только количество дней в диапазоне ----
        try:
            _, total_days = _list_holidays_in_range(conn, d_from, d_to, limit=None)
            msg.append("")
            msg.append(f"🎉 Праздники/выходные в диапазоне {d_from:%Y-%m-%d}…{d_to:%Y-%m-%d}:")
            msg.append(f"Импортировано {total_days} дней")
        except Exception as _e:
            logger.exception("list_holidays_in_range failed: %s", _e)
            msg.append("")
            msg.append("ℹ️ Не удалось посчитать количество праздничных/выходных дней (смотрите логи).")

        # ---- Внешние ссылки ----
        links = _year_links(d_from, d_to)
        if links:
            msg.append("")
            msg.append("🔗 Полезные ссылки по годам:")
            for y, url in links:
                msg.append(f"• {y}: <a href=\"{url}\">{url}</a>")

        await update.message.reply_text("\n".join(msg), parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        logger.exception("holidays_sync failed: %s", e)
        await update.message.reply_text(f"❌ Ошибка синхронизации: {e}")
