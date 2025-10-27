# /handlers/schedule_handlers.py
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from datetime import date as _date_cls, datetime as _dt_cls
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List
from collections import Counter
from html import escape
import logging

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database.connection import db_connection  # оставляем, если дальше понадобится
from database import time_repository as time_repo
from database.location_repository import get_locations

from logic.duty import _local_cycle_day, _phase_kind
from logic.duty import parse_date_arg
from logic.duty import resolve_slot_ddnn_alternating as resolve4
from logic.duty import resolve_slot_ddnn_alt_8 as resolve8

from handlers.absence_banner import reply_with_absence_banner
logger = logging.getLogger(__name__)


WEEKDAY_RU = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]

# Базовые окна смен (в TZ группы)
SLOT_WINDOWS: Dict[int, tuple[str, str]] = {
    0: ("08:00", "20:00"),
    1: ("08:00", "20:00"),
    2: ("20:00", "08:00"),
    3: ("20:00", "08:00"),
}

# вставить в schedule_handlers.py (рядом с другими хелперами)

def _clock_emoji_for_time(h: int, m: int) -> str:
    """
    Возвращает эмодзи часов по локальному времени старта:
      - целый час: 🕐..🕛
      - получас:   🕜..🕧
    """
    # нормализуем к 1..12
    hr = ((h - 1) % 12) + 1
    full = {
        1:"🕐", 2:"🕑", 3:"🕒", 4:"🕓", 5:"🕔", 6:"🕕",
        7:"🕖", 8:"🕗", 9:"🕘", 10:"🕙", 11:"🕚", 12:"🕛",
    }
    half = {
        1:"🕜", 2:"🕝", 3:"🕞", 4:"🕟", 5:"🕠", 6:"🕡",
        7:"🕢", 8:"🕣", 9:"🕤", 10:"🕥", 11:"🕦", 12:"🕧",
    }
    # Если минута >= 30 — показываем «полуседьмого» и т.п.; иначе — целый час.
    return half.get(hr) if m >= 30 else full.get(hr, "🕛")

def _coerce_date(x) -> _date_cls | None:
    """Приводит epoch к date: принимает date | 'YYYY-MM-DD' | None."""
    if isinstance(x, _date_cls):
        return x
    if isinstance(x, str):
        s = x.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y/%m/%d"):
            try:
                return _dt_cls.strptime(s, fmt).date()
            except Exception:
                pass
        try:
            return _dt_cls.fromisoformat(s).date()
        except Exception:
            return None
    return None

def _get_member_base_pos(m: dict) -> int:
    """Извлекает базовую позицию участника из разных возможных полей."""
    for k in ("base_pos", "pos", "position", "index", "baseIndex"):
        v = m.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except Exception:
            continue
    return 0

def _get_slot_pos(s: dict) -> int | None:
    for k in ("pos", "index", "slot", "slot_pos"):
        if k in s:
            try:
                return int(s[k])
            except Exception:
                return None
    return None

def _get_slot_name(s: dict) -> str:
    """Имя слота: name | title | caption | ''."""
    for k in ("name", "title", "caption"):
        v = s.get(k)
        if v:
            return str(v).strip()
    return ""

def _get_slot_times(s: dict) -> tuple[str, str] | tuple[None, None]:
    """Читает время слота из разных схем: start/end | start_time/end_time | from/to."""
    start = s.get("start") or s.get("start_time") or s.get("from")
    end   = s.get("end")   or s.get("end_time")   or s.get("to")
    if isinstance(start, str) and isinstance(end, str) and ":" in start and ":" in end:
        return start.strip(), end.strip()
    return (None, None)

def _member_base_pos(m: Dict[str, Any]) -> int:
    """
    Берём базовую позицию участника из разных вариантов поля.
    """
    for k in ("base_pos", "pos", "position", "slot_pos"):
        if k in m and m[k] is not None:
            try:
                return int(m[k])
            except Exception:
                pass
    return 0

def _group_display_name(info: Dict[str, Any]) -> str:
    """
    Красивое имя группы: сначала name, затем key, затем 'Группа'.
    """
    name = (info.get("name") or "").strip()
    if name:
        return name
    key = (info.get("key") or "").strip()
    return key or "Группа"

# --- вставить где-нибудь рядом с прочими хелперами ---

def _group_is_working_today(info: Dict[str, Any], on_date: date) -> bool:
    """
    Возвращает True, если у группы в этот день есть рабочая фаза.
    - standard/standart_*: Пн-Пт — рабочие дни
    - циклические профили: фаза day|night
    - профили без периода/со слотом 1× — считаем рабочим днём
    """
    pk = (info.get("profile_key") or info.get("profile") or "").strip().lower()
    period = int(info.get("period") or info.get("rotation_period_days") or 0)
    slots = info.get("slots") or []

    # Явный "офисный" 5×2
    if pk.startswith(("standard", "standart")):
        return on_date.weekday() < 5  # Пн-Пт

    # Если 0/1 и всего один слот — трактуем как всегда-рабочий
    if period <= 1 or len(slots) <= 1:
        return True

    # Циклические: проверяем фазу
    kind = _phase_kind_for_group(info, on_date)  # 'day'|'night'|'off'
    return kind in ("day", "night")

def _kind_ru_label(info: Dict[str, Any], on_date: date) -> str:
    """Короткая подпись типа дня: 'Будний день' для 5×2, '1 День' / '1 Ночь' для циклов."""
    pk = (info.get("profile_key") or info.get("profile") or "").strip().lower()
    if pk.startswith(("standard", "standart")):
        return "Будний день" if on_date.weekday() < 5 else "Выходной"
    kind = _phase_kind_for_group(info, on_date)
    return "1 День" if kind == "day" else ("1 Ночь" if kind == "night" else "")


def _slot_label(slot: dict) -> str:
    """Имя слота: поддержка разных полей (name/title/label). Fallback — 'Слот N'."""
    for k in ("name", "title", "label"):
        val = slot.get(k)
        if val and str(val).strip():
            return str(val).strip()
    return f"Слот {slot.get('pos')}"

def _is_standard_profile(info: dict) -> bool:
    """true, если профайл 'standard*' / 'standart*' (5×2 по будням)."""
    pk = (info.get("profile_key") or info.get("profile") or "").strip().lower()
    return pk.startswith("standard") or pk.startswith("standart")

def _convert_range_hhmm(on_date: date,
                        start_hm: str,
                        end_hm: str,
                        tz_from_name: str,
                        tz_to_name: str) -> tuple[str, str, datetime]:
    """
    Перевод интервала HH:MM..HH:MM с учётом «через полночь».
    Возвращает: (HH:MM_local_start, HH:MM_local_end, local_start_datetime) — последний для сортировки.
    """
    z_from = ZoneInfo(tz_from_name)
    z_to   = ZoneInfo(tz_to_name)
    sh = time.fromisoformat(start_hm)
    eh = time.fromisoformat(end_hm)

    start_dt = datetime.combine(on_date, sh, z_from)
    end_dt   = datetime.combine(on_date, eh, z_from)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    s_loc = start_dt.astimezone(z_to)
    e_loc = end_dt.astimezone(z_to)
    return s_loc.strftime("%H:%M"), e_loc.strftime("%H:%M"), s_loc


def _norm_hhmm(v) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, time):
        return v.strftime("%H:%M")
    return ""

def _get_slots_for_group(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Слоты берём из info['slots'], иначе — из профиля (time_repo).
    Возвращаем [{'pos', 'start', 'end', 'name'}].
    """
    slots = (info.get("slots") or [])[:]
    out: List[Dict[str, Any]] = []
    if slots:
        for s in slots:
            out.append({
                "pos":   int(s.get("pos")),
                "start": _norm_hhmm(s.get("start") or s.get("start_time")),
                "end":   _norm_hhmm(s.get("end")   or s.get("end_time")),
                "name":  (s.get("name") or "").strip(),
            })
        return out

    profile_key = (info.get("profile_key") or info.get("profile") or info.get("profile_name") or "").strip()
    if not profile_key:
        return []

    for fn_name in ("get_profile_slots", "time_profile_slots", "get_time_profile_slots",
                    "get_slots_for_profile", "profile_slots"):
        fn = getattr(time_repo, fn_name, None)
        if callable(fn):
            try:
                raw = fn(profile_key) or []
            except Exception:
                raw = []
            for s in raw:
                if isinstance(s, dict):
                    pos   = int(s.get("pos") or 0)
                    start = _norm_hhmm(s.get("start") or s.get("start_time"))
                    end   = _norm_hhmm(s.get("end")   or s.get("end_time"))
                    name  = (s.get("name") or "").strip()
                else:
                    pos   = int(s[0]) if len(s) > 0 else 0
                    start = _norm_hhmm(s[1]) if len(s) > 1 else ""
                    end   = _norm_hhmm(s[2]) if len(s) > 2 else ""
                    name  = str(s[3]).strip() if len(s) > 3 else ""
                out.append({"pos": pos, "start": start, "end": end, "name": name})
            break
    return out


def _get_members_for_group(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Возвращает участников. Источники, по приоритету:
      1) info['members'] | info['users'] | info['participants']
      2) репозиторий time_repo: get_group_members / list_group_members / get_members_for_group
    Формат каждого: {user_id, first_name, last_name, username, base_pos}
    """
    # 1) прямые поля в info
    for key in ("members", "users", "participants"):
        raw = info.get(key)
        if raw:
            out: List[Dict[str, Any]] = []
            for m in raw:
                if isinstance(m, dict):
                    out.append({
                        "user_id":   int(m.get("user_id")),
                        "first_name": (m.get("first_name") or "").strip(),
                        "last_name":  (m.get("last_name") or "").strip(),
                        "username":   (m.get("username") or "").strip(),
                        "base_pos":   int(m.get("base_pos") or 0),
                    })
                else:
                    uid = int(m[0]) if len(m) > 0 else 0
                    base_pos = int(m[1]) if len(m) > 1 else 0
                    first = (m[2] if len(m) > 2 else "") or ""
                    last  = (m[3] if len(m) > 3 else "") or ""
                    uname = (m[4] if len(m) > 4 else "") or ""
                    out.append({
                        "user_id": uid, "first_name": str(first).strip(),
                        "last_name": str(last).strip(), "username": str(uname).strip(),
                        "base_pos": base_pos,
                    })
            return out

    # 2) из репозитория
    gkey = (info.get("key") or "").strip()
    if not gkey:
        return []

    for fn_name in ("get_group_members", "list_group_members", "get_members_for_group"):
        fn = getattr(time_repo, fn_name, None)
        if callable(fn):
            try:
                raw = fn(gkey) or []
            except Exception:
                raw = []
            if raw:
                norm: List[Dict[str, Any]] = []
                for m in raw:
                    if isinstance(m, dict):
                        norm.append({
                            "user_id":   int(m.get("user_id")),
                            "first_name": (m.get("first_name") or "").strip(),
                            "last_name":  (m.get("last_name") or "").strip(),
                            "username":   (m.get("username") or "").strip(),
                            "base_pos":   int(m.get("base_pos") or 0),
                        })
                    else:
                        uid = int(m[0]) if len(m) > 0 else 0
                        base_pos = int(m[1]) if len(m) > 1 else 0
                        first = (m[2] if len(m) > 2 else "") or ""
                        last  = (m[3] if len(m) > 3 else "") or ""
                        uname = (m[4] if len(m) > 4 else "") or ""
                        norm.append({
                            "user_id": uid, "first_name": str(first).strip(),
                            "last_name": str(last).strip(), "username": str(uname).strip(),
                            "base_pos": base_pos,
                        })
                return norm
    return []

# --- ГЛАВНЫЙ СБОРЩИК ПО ДАТЕ: БЕРЁМ НАЗВАНИЕ И ВРЕМЯ ИМЕННО ИЗ ПРОФИЛЯ -----

def _weekday_ru(d: date) -> str:
    return WEEKDAY_RU[d.weekday()]

def _ru_weekday(d: date) -> str:
    return WEEKDAY_RU[d.weekday()]

def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))

def _format_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")

def _tz_from_offset_hours(offset_hours: int) -> timezone:
    return timezone(timedelta(hours=int(offset_hours or 0)))

def _resolve_viewer_tz(user_id: int) -> str:
    # при необходимости подтянешь из БД; сейчас дефолт
    return "Europe/Moscow"


def _to_zoneinfo(tz) -> ZoneInfo:
    if isinstance(tz, (timezone, ZoneInfo)):
        return tz
    if isinstance(tz, str) and tz:
        try:
            return ZoneInfo(tz)
        except Exception:
            pass
    return ZoneInfo("Europe/Moscow")

def _format_range_local(date_obj: date,
                        start_hm: str,
                        end_hm: str,
                        from_tz: str,
                        to_tz: str) -> tuple[str, str, datetime, datetime]:
    """
    Переводит интервал HH:MM..HH:MM с date_obj из from_tz в to_tz.
    Корректно обрабатывает ночной слот (конец на следующие сутки).
    Возвращает: (HH:MM_local_start, HH:MM_local_end, dt_local_start, dt_local_end)
    """
    z_from = ZoneInfo(from_tz)
    z_to   = ZoneInfo(to_tz)

    sh, sm = map(int, start_hm.split(":", 1))
    eh, em = map(int, end_hm.split(":", 1))

    start_src = datetime(date_obj.year, date_obj.month, date_obj.day, sh, sm, tzinfo=z_from)
    end_src   = datetime(date_obj.year, date_obj.month, date_obj.day, eh, em, tzinfo=z_from)
    if end_src <= start_src:
        end_src += timedelta(days=1)

    start_loc = start_src.astimezone(z_to)
    end_loc   = end_src.astimezone(z_to)

    return start_loc.strftime("%H:%M"), end_loc.strftime("%H:%M"), start_loc, end_loc


def _get_group_tz(info: Dict[str, Any]) -> str:
    tz_name = (info.get("tz") or info.get("tz_name") or "").strip()
    return tz_name or "Europe/Moscow"

def _phase_kind_for_group(info: Dict[str, Any], on_date: date) -> str:
    idx = _local_cycle_day({
        "epoch": info.get("epoch"),
        "offset_days": 0,
        "tz_offset_hours": int(info.get("tz_offset_hours") or 0),
        "period": int(info.get("period") or info.get("rotation_period_days") or 4),
    }, on_date)
    return _phase_kind(idx)  # 'day'|'night'|'off'

def _member_display(m: Dict[str, Any]) -> str:
    fn = (m.get("first_name") or "").strip()
    ln = (m.get("last_name") or "").strip()
    un = (m.get("username") or "").strip()
    label = (f"{escape(fn)} {escape(ln)}").strip() or (f"@{escape(un)}" if un else str(m.get("user_id")))
    if un and f"@{un}" not in label:
        label += f" @{escape(un)}"
    return label

def _badge_location(uid: int, on_date: date, group_key: str | None = None) -> str:
    rows = get_locations(on_date, group_key)
    for r in rows:
        if int(r["user_id"]) == int(uid):
            return " 🏢" if r["location"] == "office" else " 🏠"
    return ""

# ---------- Поддержка «стандартного 5/2» профиля ----------

def _is_standard_5_2(info: Dict[str, Any]) -> bool:
    """
    Для профилей, имя которых начинается с standard_ / standart_ —
    считаем график 5/2 (пн–пт рабочие, сб–вс выходные).
    """
    pk = (info.get("profile_key") or info.get("profile") or "").strip().lower()
    return pk.startswith("standard_") or pk.startswith("standart_")


def _standard_slot_idx(info: Dict[str, Any]) -> Optional[int]:
    """Возвращает pos единственного слота (если он есть), иначе 0."""
    slots = info.get("slots") or []
    if not slots:
        return 0
    try:
        return int(slots[0].get("pos"))
    except Exception:
        return 0

def _resolve_slot_for_member(info: dict, on_date: date, base_pos: int) -> int | None:
    """
    DDNN (4 слота) при period=8:
      последовательность: 0,1,2,3,None,None,None,None
    standart_/standard_: 5×2 (сб/вс выходные)
    Остальное: классический 4-шаговый цикл.
    """
    slots = info.get("slots") or []
    epoch = info.get("epoch")
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    profile_key = (info.get("profile_key") or info.get("profile") or "").lower().strip()

    # 5×2 (будни) — один слот, сб/вс OFF
    if profile_key.startswith(("standart", "standard")):
        if on_date.weekday() >= 5:   # 5=сб, 6=вс
            return None
        return int((slots[0].get("pos") if slots else 0) or 0)

    # 8-дневный цикл с 4 слотами (DDNN + 4 OFF)
    if period == 8 and len([s for s in slots if s.get("pos") is not None]) == 4 and epoch:
        delta = (on_date - epoch).days
        seq = [0, 1, 2, 3, None, None, None, None]  # DDNN + OFF×4
        return seq[(base_pos + (delta % 8)) % 8]

    # «настоящий» 8-шаговый профиль с 8 слотами
    if period == 8 and epoch and len(slots) >= 8:
        try:
            return resolve8(epoch, 8, base_pos, on_date)
        except Exception:
            pass

    # по умолчанию — 4-шаговый (Д1,Д2,Н1,Н2)
    try:
        return resolve4(epoch, 4, base_pos, on_date)
    except Exception:
        return None

def _choose_group_window(info: Dict[str, Any], on_date: date, used_slots: List[int]) -> tuple[str, str]:
    """
    Для заголовков пустых групп выбираем окно:
      • если стандартный 5/2 — берём время единственного слота;
      • если есть использованные слоты — берём окно самого частого;
      • иначе — от фазы (day/night).
    """
    if _is_standard_profile(info) or int(info.get("period") or 0) <= 1 or len(info.get("slots") or []) <= 1:
        s0 = (info.get("slots") or [])
        if s0:
            return ((s0[0].get("start") or "08:00"), (s0[0].get("end") or "20:00"))
        return ("08:00", "20:00")

    if used_slots:
        pos, _ = Counter(used_slots).most_common(1)[0]
        if pos in SLOT_WINDOWS:
            return SLOT_WINDOWS[pos]

    kind = _phase_kind_for_group(info, on_date)
    return ("20:00", "08:00") if kind == "night" else ("08:00", "20:00")

def _group_title(info: Dict[str, Any]) -> str:
    raw = (info.get("name") or info.get("key") or "").strip()
    title = raw.replace("Смена", "Группа").strip() if raw else "Группа"
    return f"Группа {escape(title)}"

# ---------------- Формирование вывода (группировка по слоту) ----------------

def _assignments_for_date(on_date: date, viewer_tz: str | None = None) -> List[str]:
    viewer_tz = (viewer_tz or "Europe/Moscow").strip()

    groups = time_repo.list_groups() or []
    if not groups:
        return []

    rendered: list[tuple[tuple[int,int], list[str]]] = []  # (HH,MM), блок строк

    for g in groups:
        info = time_repo.get_group_info(g.get("key"))
        if not info:
            continue

        group_name = (info.get("name") or info.get("key") or "Группа").strip()
        group_tz = (info.get("tz") or info.get("tz_name") or "Europe/Moscow").strip()
        slots: list[dict] = list(info.get("slots") or [])
        members: list[dict] = list(info.get("members") or [])

        member_names: list[str] = []
        slot_label: str = ""
        any_working = False
        used_slots: list[int] = []

        sort_hm: tuple[int,int] | None = None      # <-- NEW: ключ сортировки (показываемый старт)

        for m in members:
            base_pos = _get_member_base_pos(m)
            slot_idx = _resolve_slot_for_member(info, on_date, base_pos)
            if slot_idx is None:
                continue

            slot = next((s for s in slots if _get_slot_pos(s) == int(slot_idx)), None)
            if not slot:
                continue

            used_slots.append(int(slot_idx))

            fn = (m.get("first_name") or "").strip()
            ln = (m.get("last_name") or "").strip()
            un = (m.get("username") or "").strip()
            disp = (f"{fn} {ln}".strip() or (f"@{un}" if un else str(m.get("user_id"))))
            if un and f"@{un}" not in disp:
                disp += f" @{un}"
            member_names.append(f"👤 {escape(disp)}")
            any_working = True

            s_begin, s_end = _get_slot_times(slot)
            slot_nm = _get_slot_name(slot) or _kind_ru_label(info, on_date) or "Смена"
            if s_begin and s_end:
                # формируем подпись без стрелок
                slot_label = f"🕒 {s_begin}–{s_end}, {slot_nm}"
                # ключ сортировки — по показываемому старту
                try:
                    hh, mm = map(int, s_begin.split(":", 1))
                    sort_hm = min(sort_hm, (hh, mm)) if sort_hm else (hh, mm)
                except Exception:
                    pass
            else:
                slot_label = f"🕒 {slot_nm}"

        # если в группе никто не работает — но группа «рабочая» сегодня: вывести «(нет участников)»
        if not any_working:
            if not _group_is_working_today(info, on_date):
                continue
            s_begin, s_end = _choose_group_window(info, on_date, used_slots)
            slot_nm = _kind_ru_label(info, on_date) or "Смена"
            slot_label = f"🕒 {s_begin}–{s_end}, {slot_nm}"
            try:
                hh, mm = map(int, s_begin.split(":", 1))
                sort_hm = (hh, mm)                                    # <-- NEW
            except Exception:
                sort_hm = (23, 59)

            block_lines = [
                f"Группа {escape(group_name)}",
                slot_label,
                "👤 (нет участников)",
            ]
            rendered.append((sort_hm or (23, 59), block_lines))
            continue

        # обычный путь (есть участники)
        block_lines = [f"Группа {escape(group_name)}", slot_label] + (member_names or ["👤 (нет участников)"])
        rendered.append((sort_hm or (23, 59), block_lines))

    # сортировка строго по времени начала (как показано в строке)
    rendered.sort(key=lambda x: x[0])

    lines: List[str] = []
    for _, block in rendered:
        lines.extend(block)
    return lines

def _my_assignments_compact(uid: int, on_date: date, viewer_tz: str | None = None) -> list[str]:
    """
    Возвращает список строк вида:
      HH:MM–HH:MM [→ HH:MM–HH:MM] "Название"
    """
    viewer_tz = (viewer_tz or "Europe/Moscow").strip()

    results: list[str] = []
    for g in (time_repo.list_groups() or []):
        info = time_repo.get_group_info(g.get("key"))
        if not info:
            continue

        group_tz = (info.get("tz") or info.get("tz_name") or "Europe/Moscow").strip()
        slots: list[dict] = list(info.get("slots") or [])
        me = next((m for m in info.get("members", []) if str(m.get("user_id")) == str(uid)), None)
        if not me:
            continue

        base_pos = _get_member_base_pos(me)
        slot_idx = _resolve_slot_for_member(info, on_date, base_pos)
        if slot_idx is None:
            continue

        slot = next((s for s in slots if _get_slot_pos(s) == int(slot_idx)), None)
        if not slot:
            continue

        s_begin, s_end = _get_slot_times(slot)
        nm = _get_slot_name(slot)
        if not (s_begin and s_end):
            results.append(f'"{escape(nm)}"' if nm else "(время не указано)")
            continue

        # локализацию по-прежнему можно считать для своих нужд (например, сортировки),
        # но в тексте выводим только базовое время слота группы:
        base = f"{s_begin}–{s_end}"
        results.append(base + (f' "{escape(nm)}"' if nm else ""))

    return results


async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /next
    /next <user_id|@username> — персонально
    Теперь показывает 3 дня вперёд, начиная с сегодня.
    """
    args = context.args or []
    req_uid = update.effective_user.id
    viewer_tz = _resolve_viewer_tz(req_uid)

    # персональный режим
    target_uid = None
    if args:
        a0 = args[0].strip()
        if a0.isdigit():
            target_uid = int(a0)
        elif a0.startswith("@"):
            try:
                from logic.time_groups import time_repo as _tr
            except Exception:
                _tr = None
            if _tr:
                for g in (_tr.list_groups() or []):
                    info = _tr.get_group_info(g.get("key"))
                    if not info:
                        continue
                    m = next((m for m in info.get("members", [])
                              if (m.get("username") or "").strip().lower() == a0[1:].lower()), None)
                    if m:
                        target_uid = int(m.get("user_id"))
                        break

    today = date.today()
    days = [today + timedelta(days=i) for i in range(3)]

    def _render_day_block(d: date, lines: list[str]) -> str:
        header = f"🗓 <b>{_weekday_ru(d)}, {d.strftime('%Y-%m-%d')}</b>\n"
        body = ("\n".join(f"• {l}" for l in lines)) if lines else "Смен нет."
        return header + body

    # персональный
    if target_uid is not None:
        blocks: list[str] = []
        for d in days:
            lines = _my_assignments_compact(target_uid, d, viewer_tz)
            blocks.append(_render_day_block(d, lines))
        text_html = "\n\n".join(blocks)
        await reply_with_absence_banner(update, text_html, target_uid)
        return

    # групповой
    blocks: list[str] = []
    for d in days:
        lines = _assignments_for_date(d, viewer_tz)
        blocks.append(_render_day_block(d, lines))
    text_html = "\n\n".join(blocks)
    await reply_with_absence_banner(update, text_html, req_uid)

async def my_next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    viewer_tz = _resolve_viewer_tz(uid)
    today = date.today()

    target = None
    for i in range(60):
        d = today + timedelta(days=i)
        lines = _my_assignments_compact(uid, d, viewer_tz)
        if lines:
            target = (d, lines)
            break

    if not target:
        await reply_with_absence_banner(update, "Ближайшие 60 дней смен не найдены.", uid)
        return

    on_date, lines = target
    header = f"🗓 <b>{_weekday_ru(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
    await reply_with_absence_banner(update, header + "\n".join(f"• {l}" for l in lines), uid)

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    viewer_tz = _resolve_viewer_tz(uid)
    on_date = date.today()

    lines = _assignments_for_date(on_date, viewer_tz)
    header = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
    text_html = header + ("\n".join(lines).strip() if lines else "Смен нет.")
    await reply_with_absence_banner(update, text_html, uid)

async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    viewer_tz = _resolve_viewer_tz(uid)
    on_date = date.today() + timedelta(days=1)

    lines = _assignments_for_date(on_date, viewer_tz)
    header = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
    text_html = header + ("\n".join(lines).strip() if lines else "Смен нет.")
    await reply_with_absence_banner(update, text_html, uid)

async def ondate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    viewer_tz = _resolve_viewer_tz(uid)

    if not context.args:
        await update.message.reply_text("Укажи дату: /ondate DD.MM или /ondate DD.MM.YYYY")
        return

    raw = " ".join(context.args)
    on_date = parse_date_arg(raw)
    if not on_date:
        await update.message.reply_text("Не понял дату. Пример: /ondate 05.09.2025")
        return

    lines = _assignments_for_date(on_date, viewer_tz)
    header = f"🗓 <b>{_ru_weekday(on_date)}, {on_date.strftime('%Y-%m-%d')}</b>\n"
    text_html = header + ("\n".join(lines).strip() if lines else "Смен нет.")
    await reply_with_absence_banner(update, text_html, uid)
