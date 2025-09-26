#/handlers/schedule_handlers.py ===
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List
from collections import Counter
from html import escape
from telegram import Update
from telegram.ext import ContextTypes

from database.connection import db_connection  # для определения TZ пользователя
from database import time_repository as time_repo
from database.location_repository import get_locations
from logic.duty import _local_cycle_day, _phase_kind
from logic.duty import parse_date_arg
from logic.duty import resolve_slot_ddnn_alternating as resolve4
from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

from database.absence_repository import get_absence_on_date
from datetime import date  # если ещё не импортирован
from telegram.constants import ParseMode  # для parse_mode=HTML

from handlers.absence_banner import reply_with_absence_banner

WEEKDAY_RU = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]

# Базовые окна смен (в TZ группы):
# 0,1 → день 08:00–20:00; 2,3 → ночь 20:00–08:00
SLOT_WINDOWS: Dict[int, tuple[str, str]] = {
    0: ("08:00", "20:00"),
    1: ("08:00", "20:00"),
    2: ("20:00", "08:00"),
    3: ("20:00", "08:00"),
}

def _weekday_ru(d: date) -> str:
    return WEEKDAY_RU[d.weekday()]

def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))

def _tz_from_offset_hours(offset_hours: int) -> timezone:
    return timezone(timedelta(hours=int(offset_hours or 0)))

def _get_group_tz(info: Dict[str, Any]) -> timezone | ZoneInfo:
    """
    Возвращает TZ группы:
    - сначала пробуем IANA из info['tz'] или info['tz_name']
    - иначе фиксированное смещение info['tz_offset_hours']
    - по умолчанию Europe/Moscow
    """
    tz_name = (info.get("tz") or info.get("tz_name") or "").strip()
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return _tz_from_offset_hours(int(info.get("tz_offset_hours") or 0))

def _detect_user_tz_name(user_id: int) -> Optional[str]:
    """
    Пытаемся вытащить TZ пользователя из таблицы users:
      - колонка tz или tz_name (IANA)
      - или tz_offset_hours (целое)
    Если не нашли — вернём None (дальше возьмём Europe/Moscow).
    """
    try:
        conn = db_connection.get_connection()
        cur = conn.cursor()
        # Проверим наличие нужных колонок
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='users'
        """)
        cols = {r[0] for r in cur.fetchall()}

        if 'tz' in cols or 'tz_name' in cols:
            col = 'tz' if 'tz' in cols else 'tz_name'
            cur.execute(f"SELECT {col} FROM users WHERE user_id = %s LIMIT 1", (user_id,))
            row = cur.fetchone()
            cur.close()
            if row and row[0]:
                return str(row[0]).strip()

        if 'tz_offset_hours' in cols:
            cur.execute("SELECT tz_offset_hours FROM users WHERE user_id = %s LIMIT 1", (user_id,))
            row = cur.fetchone()
            cur.close()
            if row is not None and row[0] is not None:
                # для фиксированного смещения вернём псевдо-строку
                return f"FIXED:{int(row[0])}"
        cur.close()
    except Exception:
        # не падаем — просто вернём None
        pass
    return None

def _get_user_tz(update: Update) -> timezone | ZoneInfo:
    """
    Итоговый TZ пользователя:
    - users.tz/users.tz_name → ZoneInfo(...)
    - FIXED:<h> → timezone(hours=h)
    - иначе Europe/Moscow
    """
    uid = update.effective_user.id
    tz_name = _detect_user_tz_name(uid)
    if tz_name:
        if tz_name.startswith("FIXED:"):
            try:
                off = int(tz_name.split(":", 1)[1])
                return _tz_from_offset_hours(off)
            except Exception:
                pass
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    # дефолт
    return ZoneInfo("Europe/Moscow")

def _convert_range_for_user(on_date: date,
                            start_hhmm: str,
                            end_hhmm: str,
                            tz_from,
                            tz_to) -> tuple[str, str]:
    """
    Конвертирует интервал start–end на конкретную дату из tz_from в tz_to.
    Учитывает «перевал через полночь».
    Возвращает HH:MM, HH:MM (строки в локали пользователя).
    """
    s_t = _parse_hhmm(start_hhmm)
    e_t = _parse_hhmm(end_hhmm)

    start_dt = datetime.combine(on_date, s_t, tzinfo=tz_from)
    end_dt = datetime.combine(on_date, e_t, tzinfo=tz_from)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    start_user = start_dt.astimezone(tz_to)
    end_user = end_dt.astimezone(tz_to)

    return start_user.strftime("%H:%M"), end_user.strftime("%H:%M")

def _phase_kind_for_group(info: Dict[str, Any], on_date: date) -> str:
    idx = _local_cycle_day({
        "epoch": info.get("epoch"),
        "offset_days": 0,
        "tz_offset_hours": int(info.get("tz_offset_hours") or 0),
        "period": int(info.get("period") or info.get("rotation_period_days") or 4),
    }, on_date)
    return _phase_kind(idx)  # 'day'|'night'|'off'

def _slot_idx_for_member(info: Dict[str, Any], on_date: date, base_pos: int) -> Optional[int]:
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    if period == 8:
        return resolve8(epoch, 8, base_pos, on_date)
    return resolve4(epoch, 4, base_pos, on_date)

def _choose_group_window(info: Dict[str, Any], on_date: date, used_slots: List[int]) -> tuple[str, str]:
    """
    Выбираем базовое окно смены (в TZ группы) для заголовка:
    - если у участников есть слоты → берем самый частый слот и его окно;
    - иначе → от фазы day/night выбираем 08–20 или 20–08.
    """
    if used_slots:
        pos, _ = Counter(used_slots).most_common(1)[0]
        if pos in SLOT_WINDOWS:
            return SLOT_WINDOWS[pos]

    # fallback по фазе
    kind = _phase_kind_for_group(info, on_date)
    if kind == "night":
        return ("20:00", "08:00")
    else:
        return ("08:00", "20:00")

def _group_display_name(info: Dict[str, Any]) -> str:
    name = (info.get("name") or "").strip()
    return name or str(info.get("key") or "Группа")

def _member_line(m: Dict[str, Any], label: str) -> str:
    fn = (m.get("first_name") or "").strip()
    ln = (m.get("last_name") or "").strip()
    un = (m.get("username") or "").strip()
    display = (f"{fn} {ln}".strip() or (f"@{un}" if un else str(m.get("user_id"))))
    if un and f"@{un}" not in display:
        display += f" @{un}"
    return f'• {display} — "{label}"'

def _member_display(m: Dict[str, Any]) -> str:
    fn = (m.get("first_name") or "").strip()
    ln = (m.get("last_name") or "").strip()
    un = (m.get("username") or "").strip()
    label = (f"{escape(fn)} {escape(ln)}").strip() or (f"@{escape(un)}" if un else str(m.get("user_id")))
    if un and f"@{un}" not in label:
        label += f" @{escape(un)}"
    return label

def _slot_line(slot: Dict[str, Any]) -> str:
    # slot: {"pos": int, "start": "HH:MM", "end": "HH:MM", "name": "..."}
    nm = escape(slot.get("name") or "")
    return f"{slot['start']}–{slot['end']} {nm} (слот {slot['pos']})"

def _resolve_slot_for_member(info: Dict[str, Any], on_date: date, base_pos: int) -> Optional[int]:
    """Вернёт индекс слота (int) или None (если отдых в period=8)."""
    epoch = info.get("epoch")                      # date
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    if period == 8:
        return resolve8(epoch, 8, base_pos, on_date)
    # по умолчанию считаем 4 (ДД/НН без OFF)
    return resolve4(epoch, 4, base_pos, on_date)

# ── helper: заголовок группы «Группа <Имя>» ─────────────────────────────────────
def _group_title(info: Dict[str, Any]) -> str:
    # В БД имя профиля обычно «Смена Фамилия» → показываем «Группа Фамилия»
    raw = (info.get("name") or info.get("key") or "").strip()
    title = raw.replace("Смена", "Группа").strip() if raw else "Группа"
    return f"👷 {escape(title)}"


# ── НОВОЕ ОФОРМЛЕНИЕ ДЛЯ ОБЗОРА ПО ВСЕМ ГРУППАМ (/next без аргументов) ─────────
def _assignments_for_date(on_date: date) -> List[str]:
    """
    Собирает расписание всех групп на дату on_date в формате:

    🗓 Воскресенье, 2025-09-21
    👷 Группа Арчаков
    • Имя @username
    Название слота 🏢/🏠
    ...
    """
    lines: List[str] = []
    groups = time_repo.list_groups()  # [{'key', 'profile_key', ...}]
    if not groups:
        return lines

    for g in groups:
        info = time_repo.get_group_info(g["key"])
        if not info:
            continue

        # Какие участники реально работают в эту дату
        slots = info.get("slots", []) or []
        members = info.get("members", []) or []
        group_block: List[str] = []

        # Заголовок группы
        group_block.append(_group_title(info))

        # Детализация участников
        any_working = False
        for m in members:
            base_pos = int(m.get("base_pos") or 0)
            slot_idx = _resolve_slot_for_member(info, on_date, base_pos)
            if slot_idx is None:
                # День отдыха (в 8-дневной схеме OFF) — пропускаем
                continue

            slot = next((s for s in slots if s.get("pos") == slot_idx), None)
            if not slot:
                continue

            # 1-я строка — «• Имя @username»
            display = _member_display(m)
            group_block.append(f"• {display}")

            # 2-я строка — «<Название слота> [🏢/🏠]»
            slot_name = (slot.get("name") or "").strip()
            if not slot_name:
                # Фоллбек на краткое имя, если название пустое
                slot_name = f"Слот {slot.get('pos')}"
            badge = _badge_location(int(m.get("user_id")), on_date, info.get("key"))
            group_block.append(f"{escape(slot_name)}{badge}")

            any_working = True

        # Если в группе никто не работает в этот день — не шумим пустым блоком
        if not any_working:
            continue

        # Добавим блок и пустую строку-разделитель
        lines.extend(group_block)
        lines.append("")

    # Уберём последний лишний перенос, если он есть
    if lines and lines[-1] == "":
        lines.pop()

    return lines

def _my_assignments_for_date(uid: int, on_date: date) -> List[str]:
    """Возвращает строки только по заданному пользователю."""
    lines: List[str] = []
    groups = time_repo.list_groups()
    for g in groups:
        info = time_repo.get_group_info(g["key"])
        if not info:
            continue

        me = next((m for m in info.get("members", []) if int(m.get("user_id")) == int(uid)), None)
        if not me:
            continue

        # вычисляем слот
        slot_idx = _resolve_slot_for_member(info, on_date, int(me.get("base_pos") or 0))
        if slot_idx is None:
            # отдых — покажем явно
            lines.append(
                f"• <b>{escape(info['key'])}</b> — выходной (отдых)"
            )
            continue

        slots = info.get("slots", [])
        slot = next((s for s in slots if s["pos"] == slot_idx), None)
        if slot:
            lines.append(
                f"• <b>{escape(info['key'])}</b> — {_slot_line(slot)}"
            )
        else:
            lines.append(
                f"• <b>{escape(info['key'])}</b> — слот {slot_idx}"
            )
    return lines

def _ru_weekday(d: date) -> str:
    names = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    return names[d.weekday()]

def _my_assignments_compact(uid: int, on_date: date) -> list[str]:
    """
    Вернёт список коротких строк для конкретного пользователя на заданную дату:
    формат: HH:MM–HH:MM "Название"
    Группы не упоминаем, только сами слоты. Если ничего — вернём [].
    """
    results: list[str] = []
    for g in (time_repo.list_groups() or []):
        info = time_repo.get_group_info(g["key"])
        if not info:
            continue

        me = next((m for m in info.get("members", []) if int(m.get("user_id")) == int(uid)), None)
        if not me:
            continue

        epoch = info.get("epoch")                       # date
        period = int(info.get("period") or info.get("rotation_period_days") or 4)
        base_pos = int(me.get("base_pos") or 0)

        # выберем нужный резолвер
        if period == 8 and resolve8 is not None:
            slot_idx = resolve8(epoch, period, base_pos, on_date)
        else:
            slot_idx = resolve4(epoch, 4, base_pos, on_date)

        if slot_idx is None:
            # день отдыха в 8-дневной схеме — просто не добавляем строку (пусть выйдет "Выходной")
            continue

        slot = next((s for s in info.get("slots", []) if s["pos"] == slot_idx), None)
        if not slot:
            continue

        start = slot["start"]
        end = slot["end"]
        name = (slot.get("name") or "").strip()
        if name:
            results.append(f'{start}–{end} "{escape(name)}"')
        else:
            results.append(f"{start}–{end}")

    return results

# === REPLACE my_next_command WITH THIS ===
async def my_next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Находит ближайший день (до 60 дней вперёд), когда у текущего пользователя есть смена(ы),
    формирует краткий список слотов и отправляет через reply_with_absence_banner.
    """
    uid = update.effective_user.id
    today = date.today()

    # ищем ближайшую дату со сменой для пользователя
    target = None
    for i in range(0, 60):
        d = today + timedelta(days=i)
        lines = _my_assignments_compact(uid, d)
        if lines:
            target = (d, lines)
            break

    if not target:
        text_html = "Ближайшие 60 дней смен не найдены."
        user_id = update.effective_user.id
        await reply_with_absence_banner(update, text_html, user_id)
        return

    on_date, lines = target
    # Заголовок с датой в формате YYYY-MM-DD (нужно для баннера)
    header = f"🗓 <b>{_weekday_ru(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
    body = "\n".join(f"• {l}" for l in lines)
    text_html = header + body

    user_id = update.effective_user.id
    await reply_with_absence_banner(update, text_html, user_id)


# === REPLACE next_command WITH THIS ===
async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Два режима:
      - /next                -> ближайший день со сменами по всем группам (групповой обзор)
      - /next <user_id|@u>   -> ближайший день со сменой КОНКРЕТНОГО пользователя
    В обоих режимах добавляем баннер отпуск/больничный для того user_id, чей next показываем.
    Без аргументов — баннер для автора команды (его отсутствие).
    """
    args = context.args or []
    req_uid = update.effective_user.id

    # --- режим 1: целевой пользователь указан ---
    target_uid = None
    if args:
        a0 = args[0].strip()
        if a0.isdigit():
            target_uid = int(a0)
        elif a0.startswith("@"):
            # найдём по username в участниках групп
            for g in (time_repo.list_groups() or []):
                info = time_repo.get_group_info(g["key"])
                if not info:
                    continue
                m = next((m for m in info.get("members", [])
                          if (m.get("username") or "").strip().lower() == a0[1:].lower()), None)
                if m:
                    target_uid = int(m.get("user_id"))
                    break

    if target_uid is not None:
        # персональный next (как в /my_next, но по чужому user_id)
        today = date.today()
        target = None
        for i in range(60):
            d = today + timedelta(days=i)
            lines = _my_assignments_compact(target_uid, d)
            if lines:
                target = (d, lines)
                break

        if not target:
            text_html = "Ближайшие 60 дней смен не найдены."
            await reply_with_absence_banner(update, text_html, target_uid)
            return

        on_date, lines = target
        header = f"🗓 <b>{_weekday_ru(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
        body = "\n".join(f"• {l}" for l in lines)
        text_html = header + body
        await reply_with_absence_banner(update, text_html, target_uid)
        return

    # --- режим 2: групповой обзор (как раньше) ---
    today = date.today()
    target = None
    for i in range(60):
        d = today + timedelta(days=i)
        lines = _assignments_for_date(d)  # возвращает список строк по ВСЕМ группам на дату
        if lines:
            target = (d, lines)
            break

    if not target:
        text_html = "Ближайшие 60 дней по группам смен не найдены."
        await reply_with_absence_banner(update, text_html, req_uid)
        return

    on_date, lines = target
    header = f"🗓 <b>{_weekday_ru(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
    body = "\n".join(lines).strip()
    text_html = header + body

    # Баннер показываем для автора команды (его отсутствие), т.к. обзор групповой
    await reply_with_absence_banner(update, text_html, req_uid)

# === FIX TODAY/TOMORROW/ONDATE ===

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    on_date = date.today()

    lines = _assignments_for_date(on_date)  # уже добавляет 🏢/🏠 внутри
    if not lines:
        text_html = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\nСмен нет."
    else:
        header = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
        text_html = header + "\n".join(lines).strip()

    await reply_with_absence_banner(update, text_html, uid)


async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    on_date = date.today() + timedelta(days=1)

    lines = _assignments_for_date(on_date)
    if not lines:
        text_html = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\nСмен нет."
    else:
        header = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
        text_html = header + "\n".join(lines).strip()

    await reply_with_absence_banner(update, text_html, uid)


async def ondate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Укажи дату: /ondate DD.MM или /ondate DD.MM.YYYY")
        return

    raw = " ".join(context.args)
    # передадим TZ пользователя, чтобы корректно подставить год, если он опущен
    on_date = parse_date_arg(raw)
    if not on_date:
        await update.message.reply_text("Не понял дату. Пример: /ondate 05.09.2025")
        return

    lines = _assignments_for_date(on_date)
    if not lines:
        text_html = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\nСмен нет."
    else:
        header = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
        text_html = header + "\n".join(lines).strip()

    await reply_with_absence_banner(update, text_html, uid)

def _badge_location(uid: int, on_date: date, group_key: str | None = None) -> str:
    rows = get_locations(on_date, group_key)
    for r in rows:
        if int(r["user_id"]) == int(uid):
            return " 🏢" if r["location"] == "office" else " 🏠"
    return ""

