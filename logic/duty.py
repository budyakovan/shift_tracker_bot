# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta, time
from typing import Optional, List, Dict
import re

from database import group_repository


CYCLE_LEN = 8

# Рабочие сутки в 8-дневном цикле: 0..3 (Д1, Д2, Н1, Н2)
ON_DAYS = {0, 1, 2, 3}


def weekday_ru(d: date) -> str:
    names = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    return names[d.weekday()]

def _group_ref_start(g: Dict) -> date:
    """
    Для группы берём:
      - g['epoch'], если задана (своя эпоха), иначе
      - BASE_EPOCH + offset_days (сдвиг от базовой группы).
    """
    if g.get("epoch"):
        # в repo epoch уже тип date
        return g["epoch"]
    return BASE_EPOCH + timedelta(days=int(g.get("offset_days", 0) or 0))

def _local_cycle_day(g: Dict, d: date) -> int:
    offset_h = int(g.get("tz_offset_hours", 0) or 0)
    pivot = datetime.combine(d, time(12, 0))
    d_local = (pivot + timedelta(hours=offset_h)).date()

    ref = _group_ref_start(g)
    delta = (d_local - ref).days
    period = int(g.get("period") or CYCLE_LEN)  # если в БД period=8 — возьмём его
    if period <= 0:
        period = CYCLE_LEN
    return delta % period

def _find_duty_groups(d: date) -> List[Dict]:
    groups = group_repository.list_groups()
    # показываем только те, у кого сегодня рабочая фаза
    return [g for g in groups if _local_cycle_day(g, d) in ON_DAYS]


def _list_staff(group_key: str) -> List[Dict]:
    return group_repository.list_users_in_group(group_key)

# -------- вычисление слота по схеме ДД/НН с чередованием внутри пары --------

def resolve_slot_ddnn_alternating(epoch: date, period: int, base_pos: int, day: date) -> int:
    """
    4-дневная схема (Д1, Д2, Н1, Н2) с чередованием внутри пары.
    Слоты профиля:
      0: Полный день, 1: Короткий день, 2: Полная ночь, 3: Короткая ночь
    base_pos ∈ {0,1}
    """
    if period <= 0:
        period = 4
    d = (day - epoch).days % period
    if d == 0:   # Д1
        return base_pos            # 0→0, 1→1
    if d == 1:   # Д2
        return 1 - base_pos        # 0→1, 1→0
    if d == 2:   # Н1
        return base_pos + 2        # 0→2, 1→3
    return 3 - base_pos            # Н2: 0→3, 1→2

def resolve_slot_ddnn_alt_8(epoch: date, period: int, base_pos: int, day: date):
    """
    8-дневная схема (Д1, Д2, Н1, Н2, OFF, OFF, OFF, OFF).
    Возвращает индекс слота (0..3) или None для OFF.
    """
    if period <= 0:
        period = 8
    d = (day - epoch).days % period
    if d == 0:   # Д1
        return base_pos            # 0→0, 1→1
    if d == 1:   # Д2
        return 1 - base_pos        # 0→1, 1→0
    if d == 2:   # Н1
        return base_pos + 2        # 0→2, 1→3
    if d == 3:   # Н2
        return 3 - base_pos        # 0→3, 1→2
    return None

def build_duty_message(d: date, requester_id: int) -> str:
    duty_groups = _find_duty_groups(d)
    wday = weekday_ru(d)
    header = f"📅 {d.strftime('%d.%m.%Y')} ({wday})"
    if not duty_groups:
        return f"{header}\n🤷 На эту дату дежурные группы не найдены."

    my_group = group_repository.get_user_group(requester_id)
    my_key = my_group["key"] if my_group else None

    # Разнесём по секциям (дневные/ночные фазы этого дня)
    day_items, night_items = [], []
    for g in duty_groups:
        idx = _local_cycle_day(g, d)
        kind = _phase_kind(idx)
        if kind == "day":
            day_items.append((g, idx))
        elif kind == "night":
            night_items.append((g, idx))

    # Мою группу — первой в своей секции
    def _sort(items):
        return sorted(items, key=lambda t: 0 if t[0].get("key") == my_key else 1)

    day_items = _sort(day_items)
    night_items = _sort(night_items)

    parts = [header]

    def _section(title, items):
        if not items:
            return
        parts.append(title)
        for g, idx in items:
            users = _list_staff(g["key"])
            is_mine = (g["key"] == my_key)
            tz_text = g["tz_name"] or (f"MSK{int(g.get('tz_offset_hours', 0)):+d}h")
            phase = _phase_label(idx)
            em = _phase_emoji(idx)

            if is_mine:
                parts.append("✅ Мы дежурим")
            else:
                parts.append(f"👷 \"{g.get('name') or g.get('key')}\" ({g['key']}, {tz_text})")

            parts.append(f"{em} {phase}")

            if users:
                for u in users:
                    full_name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
                    uname = f"@{u['username']}" if u.get('username') else ""
                    label = (full_name or uname or str(u['user_id'])).strip()
                    tail = f" {uname}" if (uname and uname not in label) else ""
                    parts.append(f"• {label}{tail}")
            else:
                parts.append("• (нет зарегистрированных сотрудников)")

            parts.append("─" * 20)

    _section("Дневные смены:", day_items)
    _section("Ночные смены:", night_items)

    return "\n".join(parts)

# -------- парсер даты для /ondate --------

_DATE_RE = re.compile(r"^\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\s*$")

def parse_date_arg(raw: str, *, user_tz=None) -> date | None:
    """
    Поддерживает:
      - DD.MM.YYYY   (например, 24.09.2025)
      - D.M.YYYY
      - DD.MM        (год берётся текущий в TZ пользователя)
      - YYYY-MM-DD   (ISO)
    Возвращает date или None.
    """
    raw = (raw or "").strip()

    # ISO: YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # DD.MM.YYYY / D.M.YYYY
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw)
    if m:
        d, mth, y = map(int, m.groups())
        try:
            return date(y, mth, d)
        except ValueError:
            return None

    # DD.MM / D.M  (без года → подставляем текущий год в TZ пользователя)
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", raw)
    if m:
        d, mth = map(int, m.groups())
        if user_tz is None:
            # используем TZ пользователя, если можешь его получить
            try:
                user_tz = _get_user_tz  # ссылка на функцию; если нет — ниже fallback
            except Exception:
                user_tz = None
        try:
            if callable(user_tz):
                y = datetime.now(user_tz(update=None) if user_tz.__code__.co_argcount else user_tz).year  # на случай другой сигнатуры
            else:
                y = datetime.now().year
        except Exception:
            y = datetime.now().year
        try:
            return date(y, mth, d)
        except ValueError:
            return None

    return None

def _phase_label(day_idx: int) -> str:
    """
    0..3 — рабочие: 0=1 день, 1=2 день, 2=1 ночь, 3=2 ночь
    с периодом 4 «выходной» не наступает, но оставим для совместимости
    """
    mapping = {0: "1 день", 1: "2 день", 2: "1 ночь", 3: "2 ночь"}
    return mapping.get(day_idx, "выходной")

def _phase_emoji(day_idx: int) -> str:
    # 0,1 = день → ☀️ ; 2,3 = ночь → 🌙 ; иначе пусто
    return "☀️" if day_idx in (0, 1) else ("🌙" if day_idx in (2, 3) else "")

def _phase_kind(day_idx: int) -> str:
    # 0,1 = день; 2,3 = ночь; остальное — выходной (для period=4 не используется)
    return "day" if day_idx in (0, 1) else ("night" if day_idx in (2, 3) else "off")
