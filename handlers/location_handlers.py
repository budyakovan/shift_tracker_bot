# /home/telegrambot/shift_tracker_bot/handlers/location_handlers.py
# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta, time as _time
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from html import escape
from logic.duty import _local_cycle_day, _phase_kind
from database.pair_repository import get_pair_day
from database.rank_rotation_repository import get_rule as get_rank_rotation_rule
from database.rank_repository import get_member_rank_effective as _rank_eff, get_member_rank as _rank_base

import database.users_repository as user_repository
from database.location_repository import (
    assign_locations_for_group_filtered,
    get_locations,
    office_report,
    get_office_days_count,
    _pairs_indexed_for_subset,
    get_group_locations_today,
    get_location_map_for_users_on,
)
from database import time_repository as time_repo
from database import group_repository
from handlers.help_texts import HELP_LOCATION_SHORT
from database.absence_repository import get_absence_on_date

# best-effort доступ к полному модулю location_repository для ручного апсёрта
try:
    import database.location_repository as loc_repo
except Exception:
    loc_repo = None


def _is_admin(uid: int) -> bool:
    ur = user_repository
    try:
        return bool(getattr(ur, "is_user_admin")(uid))
    except Exception:
        return False


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _find_user_time_group_key(uid: int) -> str | None:
    """
    Fallback: ищем тайм-группу пользователя через time_repository,
    если group_repository не вернул ничего.
    Проходим по всем группам и смотрим members.
    """
    try:
        groups = (getattr(time_repo, "list_groups")() or [])
        # list_groups может возвращать разные структуры; достанем ключи надёжно
        keys: list[str] = []
        for g in groups:
            # допускаем варианты: {"key": "..."} или кортежи/списки
            if isinstance(g, dict) and "key" in g:
                keys.append(str(g["key"]))
            elif isinstance(g, (list, tuple)) and g:
                keys.append(str(g[0]))
        keys = list(dict.fromkeys(keys))  # uniq, preserve order
        for k in keys:
            info = getattr(time_repo, "get_group_info")(k) or {}
            for m in (info.get("members") or []):
                try:
                    if int(m.get("user_id")) == int(uid):
                        return str(k)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _is_night_slot_local(start_hhmm: str, end_hhmm: str) -> bool:
    """Ночь = интервал, пересекающий 00:00."""
    from datetime import datetime, date, time as _t

    def _parse_hhmm(s: str) -> _t:
        hh, mm = s.split(":")
        return _t(int(hh), int(mm))

    s = _parse_hhmm(start_hhmm)
    e = _parse_hhmm(end_hhmm)
    return (datetime.combine(date.today(), e) <= datetime.combine(date.today(), s))


def _effective_rank_for_day(group_key: str, uid: int, on_date: date) -> int | None:
    """Ранг 1..3 на дату с фолбэками."""
    try:
        r = _rank_eff(str(group_key), int(uid), on_date)
        if r in (1, 2, 3):
            return int(r)
    except Exception:
        pass
    try:
        r = _rank_base(str(group_key), int(uid))
        if r in (1, 2, 3):
            return int(r)
    except Exception:
        pass
    try:
        gi = time_repo.get_group_info(str(group_key)) or {}
        for m in gi.get("members", []) or []:
            if int(m.get("user_id")) == int(uid):
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


def _rotation_offset_for(group_key: str, on_date: date) -> int | None:
    """offset = floor((on_date - epoch)/period_days) из rank_rotation_rules; None если нет правила."""
    try:
        rule = get_rank_rotation_rule(str(group_key))
        if not rule or not rule.get("is_enabled"):
            return None
        ep = rule.get("epoch")
        pd = int(rule.get("period_days") or 0)
        if not ep or pd <= 0:
            return None
        return max(0, (on_date - ep).days // pd)
    except Exception:
        return None


def _compute_pairs_for_day(group_key: str, on_date: date) -> dict[int, int]:
    """
    Возвращает карту партнёров для ДНЕВНОГО слота: uid -> partner_uid.
    Приоритет:
      1) Журнал pair_work_log (get_pair_day)
      2) Ротация рангов (1↔2) по текущему offset среди дневных on-duty
    """
    # 1) точная пара из журнала
    try:
        pair = get_pair_day(str(group_key), on_date)
        if pair and isinstance(pair, (tuple, list)) and len(pair) == 2:
            a, b = int(pair[0]), int(pair[1])
            if a and b and a != b:
                return {a: b, b: a}
    except Exception:
        pass

    # 2) рассчитать по ротации для дневных on-duty
    try:
        from database.location_repository import get_on_duty_members

        members = get_on_duty_members(str(group_key), on_date) or []
        day_uids: list[int] = []
        for m in members:
            st = str(m["slot"].get("start"))
            en = str(m["slot"].get("end"))
            if not _is_night_slot_local(st, en):
                day_uids.append(int(m["user_id"]))
        if not day_uids:
            return {}

        seniors: list[int] = []
        specs: list[int] = []
        for uid in sorted(set(day_uids)):
            r = _effective_rank_for_day(group_key, uid, on_date)
            if r == 1:
                seniors.append(uid)
            elif r == 2:
                specs.append(uid)

        if not seniors or not specs:
            return {}

        off = _rotation_offset_for(group_key, on_date)
        if off is None:
            off = 0

        partners: dict[int, int] = {}
        n = len(specs)
        for i, sp in enumerate(sorted(seniors)):
            s = specs[(i + off) % n]
            partners[sp] = s
            partners[s] = sp
        return partners
    except Exception:
        return {}


def _is_night_interval(start_hhmm: str, end_hhmm: str) -> bool:
    """
    True, если интервал [start,end) пересекает полночь (ночной слот).
    Примеры ночи: 20:00–08:00, 22:00–04:00. День: 08:00–20:00, 09:00–18:00.
    Парсит 'HH:MM' (допускает '8:00' / '08:00').
    """
    def _parse_hhmm(s: str):
        s = (s or "").strip()
        try:
            # принимает как '8:00', так и '08:00'
            return datetime.strptime(s, "%H:%M").time()
        except Exception:
            hh, mm = s.split(":")
            return datetime(2000, 1, 1, int(hh), int(mm)).time()

    s = _parse_hhmm(start_hhmm)
    e = _parse_hhmm(end_hhmm)
    # ночь, если конец не позже начала (т.е. прошёл через полночь)
    return datetime.combine(date(2000, 1, 1), e) <= datetime.combine(date(2000, 1, 1), s)


def _group_slot_name_for_date(group_key: str, on_date: date) -> tuple[str | None, bool]:
    """
    Возвращает (человеческое имя слота, is_night) для группы на дату.
    Берём первый найденный активный слот участника на on_date.
    Пример имени: '1 День', '2 Ночь' — это поле 'name' из конфигурации слотов.
    """
    try:
        gi = time_repo.get_group_info(str(group_key)) or {}
        members = gi.get("members") or []
        slots = gi.get("slots") or []
        if not members or not slots:
            return (None, False)

        # индекс слотов → слоты
        slots_by_pos = {int(s["pos"]): s for s in slots}

        # как в duty: резолвим индекс слота участника на дату
        from logic.duty import resolve_slot_ddnn_alternating as resolve4
        from logic.duty import resolve_slot_ddnn_alt_8 as resolve8
        period = int(gi.get("period") or gi.get("rotation_period_days") or 4)
        epoch = gi.get("epoch")

        for m in members:
            base_pos = 0
            for k in ("base_pos", "pos", "position", "slot_pos"):
                v = m.get(k)
                if v is not None:
                    try:
                        base_pos = int(v)
                        break
                    except Exception:
                        pass
            slot_idx = resolve8(epoch, 8, base_pos, on_date) if period == 8 else resolve4(epoch, 4, base_pos, on_date)
            if slot_idx is None:
                continue
            sl = slots_by_pos.get(int(slot_idx))
            if not sl:
                continue
            name = str(sl.get("name") or "").strip() or None
            start = sl.get("start")
            end = sl.get("end")
            if start and end:
                is_night = _is_night_interval(str(start), str(end))
            else:
                # если нет времени — считаем дневным
                is_night = False
            return (name, is_night)
    except Exception:
        pass
    return (None, False)


def _pair_mark(a: int, b: int, mark_map: dict[tuple[int, int], str], palette: list[str]) -> str:
    """
    Даёт стабильный «цветной ромбик» для пары (a,b).
    Пара нормализуется к (min,max) и получает следующий символ из palette по кругу.
    """
    key = (a, b) if a < b else (b, a)
    if key not in mark_map:
        mark_map[key] = palette[len(mark_map) % len(palette)]
    return mark_map[key]


def _partners_for_set(group_key: str, on_date: date, uids: list[int]) -> dict[int, int]:
    """
    Сформировать пары СП(1)↔С(2) по активной ротации для указанного множества uids.
    Возвращает карту uid -> partner_uid. Если лидеров или специалистов нет — пусто.
    """
    try:
        off = _rotation_offset_for(group_key, on_date)
        if off is None:
            off = 0
        seniors: list[int] = []
        specs: list[int] = []
        for uid in sorted(set(int(x) for x in uids)):
            r = _effective_rank_for_day(group_key, uid, on_date)
            if r == 1:
                seniors.append(uid)
            elif r == 2:
                specs.append(uid)
        if not seniors or not specs:
            return {}

        partners: dict[int, int] = {}
        n = len(specs)
        for i, sp in enumerate(sorted(seniors)):
            s = specs[(i + off) % n]
            partners[sp] = s
            partners[s] = sp
        return partners
    except Exception:
        return {}


def _compute_pairs_for_date(group_key: str, on_date: date) -> dict[int, int]:
    """
    Пары для ДНЯ и НОЧИ (обеих частей суток).
    Берём on-duty участников → делим на дневных и ночных → строим пары в каждой подгруппе.
    """
    try:
        from database.location_repository import get_on_duty_members

        members = get_on_duty_members(str(group_key), on_date) or []
        day_uids: list[int] = []
        night_uids: list[int] = []

        for m in members:
            st = str(m["slot"].get("start"))
            en = str(m["slot"].get("end"))
            if _is_night_interval(st, en):
                night_uids.append(int(m["user_id"]))
            else:
                day_uids.append(int(m["user_id"]))

        partners: dict[int, int] = {}
        if day_uids:
            partners.update(_partners_for_set(group_key, on_date, day_uids))
        if night_uids:
            partners.update(_partners_for_set(group_key, on_date, night_uids))
        return partners
    except Exception:
        return {}


async def loc_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_assign
      → 1 день вперёд для своей группы
    /loc_assign <N>
      → N дней вперёд для своей группы
    /loc_assign <group_key>
      → 1 день вперёд для указанной группы
    /loc_assign <N> <group_key>
      → N дней вперёд для указанной группы
    /loc_assign <YYYY-MM-DD> [<group_key>]
      → назначить на конкретную дату
    /loc_assign <YYYY-MM-DD> <N> [<group_key>]
      → N дней начиная с указанной даты
    /loc_assign <YYYY-MM-DD> <YYYY-MM-DD> [<group_key>]
      → диапазон дат (включительно)

    Исключаем отпуск/больничный на соответствующие дни. Назначаем независимо от дня/ночи.
    """
    user_id = update.effective_user.id
    args = context.args or []

    # --- определяем группу инициатора ---
    try:
        user_grp = group_repository.get_user_group(user_id) or {}
        if isinstance(user_grp, dict):
            initiator_group = user_grp.get("key")
        elif user_grp:
            initiator_group = str(user_grp)
        else:
            initiator_group = None
    except Exception:
        initiator_group = None
    initiator_group = initiator_group or _find_user_time_group_key(user_id)

    n_days = 1
    explicit_group: str | None = None
    start_date = date.today()

    # --- парсинг аргументов ---
    def _try_parse_date(s: str):
        try:
            return date.fromisoformat(s)
        except Exception:
            return None

    if len(args) == 0:
        pass
    elif len(args) == 1:
        a1 = args[0].strip()
        d1 = _try_parse_date(a1)
        if d1:
            start_date = d1
            n_days = 1
        else:
            try:
                n_days = int(a1)
            except ValueError:
                explicit_group = a1
    elif len(args) >= 2:
        a1, a2 = args[0].strip(), args[1].strip()
        d1, d2 = _try_parse_date(a1), _try_parse_date(a2)

        if d1 and d2:
            # диапазон дат
            start_date = d1
            n_days = max(1, (d2 - d1).days + 1)
            if len(args) >= 3:
                explicit_group = args[2].strip()
        elif d1 and not d2:
            # дата + число
            start_date = d1
            try:
                n_days = int(a2)
            except ValueError:
                await update.message.reply_text(
                    "❌ Второй аргумент должен быть числом дней или датой в формате YYYY-MM-DD."
                )
                return
            if len(args) >= 3:
                explicit_group = args[2].strip()
        elif not d1:
            # число + группа
            try:
                n_days = int(a1)
            except ValueError:
                await update.message.reply_text(
                    "❌ Первый аргумент должен быть числом дней или датой в формате YYYY-MM-DD."
                )
                return
            if len(args) >= 2:
                explicit_group = a2

    # --- какой набор групп использовать ---
    if explicit_group:
        group_keys = [explicit_group]
    else:
        if not initiator_group:
            await update.message.reply_text(
                "🪪 Твоя группа не назначена. Укажи явно: /loc_assign <group_key>."
            )
            return
        group_keys = [str(initiator_group)]

    total_assigned = 0
    skipped = []  # (dt, gkey, user_disp, ab_type, d_from, d_to, comment)
    errors = []

    for i in range(n_days):
        dt = start_date + timedelta(days=i)
        for gk in group_keys:
            try:
                gi = time_repo.get_group_info(gk) or {}
                members = gi.get("members") or []
            except Exception:
                members = []

            exclude_ids: list[int] = []
            for m in members:
                uid = m.get("user_id")
                if not uid:
                    continue
                try:
                    ab = get_absence_on_date(int(uid), dt)
                except Exception:
                    ab = None
                if ab:
                    exclude_ids.append(int(uid))
                    fn = (m.get("first_name") or "").strip()
                    ln = (m.get("last_name") or "").strip()
                    un = (m.get("username") or m.get("tg_username") or "").strip()
                    disp = (f"{fn} {ln}".strip() or f"user_id={uid}") + (f" @{un}" if un else "")
                    skipped.append((
                        dt, gk, disp, ab.get("absence_type"),
                        ab.get("date_from"), ab.get("date_to"),
                        (ab.get("comment") or "").strip()
                    ))

            try:
                total_assigned += int(assign_locations_for_group_filtered(gk, dt, exclude_ids) or 0)
            except Exception as e:
                errors.append((dt, gk, str(e)))

    # --- отчёт ---
    if n_days == 1:
        head = f"📍 Локации проставлены на {start_date:%Y-%m-%d}."
    else:
        last_day = start_date + timedelta(days=n_days - 1)
        head = f"📍 Локации проставлены на период {start_date:%Y-%m-%d}…{last_day:%Y-%m-%d}."
    lines = [head, f"✅ Назначений записано: <b>{total_assigned}</b>"]

    if skipped:
        from collections import defaultdict
        bucket = defaultdict(list)
        for dt, gk, disp, ab_type, d_from, d_to, cmt in skipped:
            key = (str(gk), str(disp), str(ab_type), str(d_from), str(d_to), str(cmt))
            bucket[key].append(dt)

        lines.append("\n⛱ Внимание! Сотрудник пропущен из-за отпусков/больничных:")
        for (gk, disp, ab_type, d_from, d_to, cmt), dts in sorted(bucket.items(), key=lambda x: (min(x[1]), x[0])):
            dts.sort()
            span_from = dts[0].strftime("%Y-%m-%d")
            span_to = dts[-1].strftime("%Y-%m-%d")
            date_part = span_from if span_from == span_to else f"{span_from}…{span_to}"
            emoji = "🏖" if ab_type == "vacation" else "🤒"
            label = "отпуск" if ab_type == "vacation" else "больничный"
            cmt_part = f" — {escape(cmt, False)}" if cmt else ""
            lines.append(
                f"• {date_part} [{escape(gk, False)}]: {emoji} {escape(disp, False)} — {label} "
                f"{d_from}—{d_to}{cmt_part}"
            )

    if errors:
        lines.append("\n⚠️ Ошибки при назначении:")
        for dt, gkey, err in errors[:50]:
            lines.append(f"• {dt:%Y-%m-%d} [{escape(gkey, False)}]: {escape(err, False)}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def loc_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_report <group_key> <YYYY-MM[-DD]> [<YYYY-MM[-DD]>]

    Примеры:
      /loc_report vrn3 2025-10-01 2025-10-31   — произвольный диапазон
      /loc_report vrn3 2025-10                 — весь октябрь 2025
      /loc_report vrn3 2025-10 2025-11         — с 1 окт до 30 ноя (включительно)
      /loc_report vrn3 2025-11-01 2025-11-31   — «31 ноября» → 2025-11-30
    """
    from calendar import monthrange

    args = [a.strip() for a in (context.args or []) if a.strip()]

    # NEW: поддержка формы без явного group_key: /loc_report <YYYY-MM[-DD]> [<YYYY-MM[-DD]>]
    # В этом случае group_key берём по пользователю.
    def _looks_like_date_or_month(s: str) -> bool:
        if not s or len(s) < 7:
            return False
        parts = s.split("-")
        if len(parts) not in (2, 3):
            return False
        try:
            y = int(parts[0]); m = int(parts[1])
            return 1 <= m <= 12 and 1900 <= y <= 9999
        except Exception:
            return False

    if len(args) < 1:
        await update.message.reply_text(
            "Использование: /loc_report <group_key> <YYYY-MM[-DD]> [<YYYY-MM[-DD]>]\n"
            "Либо: /loc_report <YYYY-MM[-DD]> [<YYYY-MM[-DD]>] — для своей группы."
        )
        return

    # Определяем group_key и оставшиеся аргументы дат
    if _looks_like_date_or_month(args[0]):
        # нет явного group_key — берём по пользователю
        gkey = None
        try:
            ug = group_repository.get_user_group(update.effective_user.id) or {}
            gkey = ug.get("key") if isinstance(ug, dict) else (str(ug) if ug else None)
        except Exception:
            gkey = None
        if not gkey:
            gkey = _find_user_time_group_key(update.effective_user.id)
        if not gkey:
            await update.message.reply_text("🪪 Не удалось определить твою группу. Укажи: /loc_report <group_key> <период>.")
            return
        date_args = args
    else:
        # обычная форма: указан group_key
        gkey = args[0]
        date_args = args[1:]

    if len(date_args) < 1:
        await update.message.reply_text("Нужен период: <YYYY-MM[-DD]> [<YYYY-MM[-DD]>].")
        return

    def _parse_date_or_month(s: str, *, want_end: bool | None = None) -> date | None:
        """
        Поддерживает:
          - 'YYYY-MM-DD' (валидная дата)
          - 'YYYY-MM-DD' (если день > последнего — сдвиг к последнему дню месяца)
          - 'YYYY-MM' (возвращает 1-е число месяца, а если want_end=True — последний день)
        """
        s = s.strip()
        # Пытаемся как полную дату
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass

        parts = s.split("-")
        # Месяц без дня: YYYY-MM
        if len(parts) == 2:
            try:
                y, m = map(int, parts)
                last_day = monthrange(y, m)[1]
                d = last_day if want_end else 1
                return date(y, m, d)
            except Exception:
                return None

        # Невалидная полная дата (например, 2025-11-31) — щадяще сдвигаем к концу месяца
        if len(parts) == 3:
            try:
                y, m, d = map(int, parts)
                last_day = monthrange(y, m)[1]
                if d > last_day:
                    d = last_day
                return date(y, m, d)
            except Exception:
                return None

        return None

    # Разбор диапазона: если передан один элемент периода — строим отчёт за месяц
    if len(date_args) == 1:
        s = date_args[0]
        d1 = _parse_date_or_month(s, want_end=False)
        d2 = _parse_date_or_month(s, want_end=True)
    elif len(date_args) >= 2:
        s_from, s_to = date_args[0], date_args[1]
        # если конечная дата задана в формате YYYY-MM, берём конец месяца
        want_end_to = (len(s_to.split("-")) == 2)
        d1 = _parse_date_or_month(s_from, want_end=False)
        d2 = _parse_date_or_month(s_to, want_end=want_end_to)
    else:
        d1 = d2 = None

    if not (d1 and d2):
        await update.message.reply_text("Даты должны быть в формате YYYY-MM или YYYY-MM-DD.")
        return

    if d2 < d1:
        d1, d2 = d2, d1

    # Данные
    try:
        rows = office_report(gkey, d1, d2) or []
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при построении отчёта: {escape(str(e), False)}")
        return

    if not rows:
        await update.message.reply_text(
            "📊 Нет данных по офис-дням"
            + (f" для <b>{escape(gkey)}</b>" if gkey else "")
            + f" в период {d1:%Y-%m-%d}…{d2:%Y-%m-%d}.",
            parse_mode=ParseMode.HTML
        )
        return

    # Профили для красивого вывода
    profiles_by_uid: dict[int, dict] = {}
    try:
        gi = time_repo.get_group_info(gkey) or {}
        for m in gi.get("members", []) or []:
            uid = int(m.get("user_id"))
            fn = (m.get("first_name") or "").strip()
            ln = (m.get("last_name") or "").strip()
            full = (f"{fn} {ln}".strip() or (m.get("full_name") or m.get("name") or "")).strip() or f"ID {uid}"
            uname = (m.get("username") or m.get("user_name") or m.get("tg_username") or "").strip()
            profiles_by_uid[uid] = {"full_name": full, "username": uname}
    except Exception:
        pass

    header = (
        f"🏢 Отчёт по офис-дням для группы <b>{escape(gkey)}</b>\n"
        f"📅 Период: {d1:%Y-%m-%d}…{d2:%Y-%m-%d}\n"
    )
    lines = [header]

    # Сортировка по количеству офис-дней (по убыванию)
    for r in sorted(rows, key=lambda x: int(x.get("office_days", 0)), reverse=True):
        uid = int(r["user_id"])
        days = int(r["office_days"])
        prof = profiles_by_uid.get(uid, {})
        full = escape(prof.get("full_name") or f"ID {uid}")
        uname = prof.get("username")
        uname_part = f" 🔗 @{escape(uname)}" if uname else ""
        lines.append(f"• {full}{uname_part} — {days}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def loc_clear_future(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_clear_future [group_key]
    Удаляет все будущие назначения (on_date > today).
    Если group_key не указан — только для своей группы.
    """
    user_id = update.effective_user.id
    args = context.args or []
    from database.connection import db_connection

    # определить группу пользователя
    user_group_key = None
    try:
        grp = group_repository.get_user_group(user_id) or {}
        if isinstance(grp, dict):
            user_group_key = grp.get("key")
        elif grp:
            user_group_key = str(grp)
    except Exception:
        pass
    user_group_key = user_group_key or _find_user_time_group_key(user_id)

    if len(args) == 0:
        gk = user_group_key
    else:
        gk = args[0]

    if not gk:
        await update.message.reply_text("🪪 Не удалось определить группу. Укажи явно: /loc_clear_future <group_key>")
        return

    # админ может чистить любую группу
    if (user_group_key is None or str(gk) != str(user_group_key)) and not _is_admin(user_id):
        await update.message.reply_text("⛔ Недостаточно прав: очищать чужую группу может только админ.")
        return

    conn = db_connection.get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM location_assignments WHERE group_key=%s AND on_date > CURRENT_DATE", (gk,))
        deleted = cur.rowcount
        conn.commit()

    await update.message.reply_text(f"🧹 Удалено {deleted} будущих назначений для <code>{gk}</code>.", parse_mode="HTML")


async def loc_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_next
      → 7 дней вперёд для своей группы
    /loc_next <N>
      → N дней вперёд для своей группы
    /loc_next <group_key>
      → 7 дней вперёд для указанной группы
    /loc_next <N> <group_key>
      → N дней вперёд для указанной группы
    /loc_next <YYYY-MM-DD> [<group_key>]
      → начиная с даты (7 дней)
    /loc_next <YYYY-MM-DD> <N> [<group_key>]
      → начиная с даты N дней
    /loc_next <YYYY-MM-DD> <YYYY-MM-DD> [<group_key>]
      → диапазон дат (включительно)
    """
    args = context.args or []
    user_id = update.effective_user.id

    # --- группа инициатора ---
    try:
        grp = group_repository.get_user_group(user_id) or {}
        initiator_group = grp["key"] if isinstance(grp, dict) else (str(grp) if grp else None)
    except Exception:
        initiator_group = None
    initiator_group = initiator_group or _find_user_time_group_key(user_id)

    # --- парсинг аргументов ---
    def _try_date(s: str):
        try:
            return date.fromisoformat(s)
        except Exception:
            return None

    start_date = date.today()
    n_days = 7
    gkey = None

    if len(args) == 0:
        pass
    elif len(args) == 1:
        a1 = args[0].strip()
        d1 = _try_date(a1)
        if d1:
            start_date = d1
        else:
            try:
                n_days = int(a1)
            except ValueError:
                gkey = a1
    else:
        a1, a2 = args[0].strip(), args[1].strip()
        d1, d2 = _try_date(a1), _try_date(a2)
        if d1 and d2:
            start_date = d1
            n_days = max(1, (d2 - d1).days + 1)
            if len(args) >= 3:
                gkey = args[2].strip()
        elif d1 and not d2:
            start_date = d1
            try:
                n_days = int(a2)
            except ValueError:
                await update.message.reply_text("❌ Второй аргумент должен быть числом или датой.")
                return
            if len(args) >= 3:
                gkey = args[2].strip()
        else:
            # число + группа
            try:
                n_days = int(a1)
            except ValueError:
                await update.message.reply_text("❌ Первый аргумент должен быть числом дней или датой.")
                return
            gkey = a2

    if not gkey:
        gkey = initiator_group
    if not gkey:
        await update.message.reply_text("🪪 Твоя группа не назначена. Укажи явно: /loc_next <group_key>")
        return

    # телеграм-лимит
    if n_days > 30:
        await update.message.reply_text("⚠️ Telegram ограничивает длину сообщений, вывод сокращён до 30 дней.")
        n_days = 30

    # профили
    profiles_by_uid: dict[int, dict] = {}
    try:
        gi = time_repo.get_group_info(gkey) or {}
        for m in gi.get("members", []) or []:
            uid = int(m.get("user_id"))
            first = (m.get("first_name") or "").strip()
            last = (m.get("last_name") or "").strip()
            full_name = (f"{first} {last}".strip() or (m.get("full_name") or m.get("name") or m.get("display") or "")).strip()
            username = (m.get("username") or m.get("user_name") or m.get("tg_username") or "").strip() or None
            profiles_by_uid[uid] = {"full_name": full_name or f"ID {uid}", "username": username}
    except Exception:
        pass

    _WEEKDAY_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    def _loc_emoji(loc: str) -> str:
        return "🏢 Офис" if loc == "office" else "🏠 Дом"

    # ВЫВОД ИМЕН ТОЛЬКО ПОЛНОЕ ИМЯ (без @username)
    def _display(uid: int, join_row: dict | None = None) -> str:
        prof = profiles_by_uid.get(uid) or {}
        full = (prof.get("full_name") or (join_row or {}).get("full_name") or f"ID {uid}").strip()
        return f"{escape(full)}"

    lines = [
        f"🗓 План локаций на {n_days} дн. вперёд с {start_date:%Y-%m-%d} для <code>{escape(gkey)}</code>",
    ]

    from database.location_repository import get_on_duty_members, _pairs_indexed_for_subset  # noqa: F401

    for i in range(n_days):
        d = start_date + timedelta(days=i)

        # Берём назначения на день. Если их нет — пропускаем день целиком (НЕ показываем «— назначений нет.»)
        rows = get_locations(d, gkey)
        if not rows:
            continue

        slot_name, _ = _group_slot_name_for_date(gkey, d)
        dow = _WEEKDAY_RU[d.weekday()]
        lines.append(f"\n<b>{dow}, {d:%Y-%m-%d}</b>" + (f" — {escape(slot_name)}" if slot_name else ""))

        # индексы назначений
        by_uid = {int(r["user_id"]): r for r in rows}
        uids_sorted = sorted(by_uid.keys())

        # on-duty на дату → делим на день/ночь
        try:
            duty_members = get_on_duty_members(gkey, d) or []
        except Exception:
            duty_members = []

        day_uids, night_uids = [], []
        for m in duty_members:
            uid = int(m["user_id"])
            st, en = str(m["slot"].get("start")), str(m["slot"].get("end"))
            if _is_night_interval(st, en):
                night_uids.append(uid)
            else:
                day_uids.append(uid)

        # пары с индексами по подгруппам
        day_pairs = _pairs_indexed_for_subset(gkey, d, day_uids)  # [(a,b,idx), ...]
        night_pairs = _pairs_indexed_for_subset(gkey, d, night_uids)

        partners_all: dict[int, int] = {}
        for a, b, _ in day_pairs + night_pairs:
            partners_all[a] = b
            partners_all[b] = a

        # определим «цвет» пары по индексу (0→🔷, 1→🔶)
        color_by_uid: dict[int, str] = {}
        for a, b, idx in day_pairs + night_pairs:
            mark = "🔷" if idx == 0 else "🔶"
            color_by_uid[a] = mark
            color_by_uid[b] = mark

        # печать: сначала пары с офисом, затем прочие пары, затем одиночки
        visited: set[int] = set()
        pair_blocks_with_office: list[list[str]] = []
        pair_blocks_without_office: list[list[str]] = []
        singles: list[str] = []

        def _block_has_office(block: list[str]) -> bool:
            return any("🏢 Офис" in line for line in block)

        for uid in uids_sorted:
            if uid in visited:
                continue
            r = by_uid[uid]
            loc = str(r["location"])
            if uid in partners_all and partners_all[uid] in by_uid:
                p = partners_all[uid]
                if p in visited:
                    continue
                visited.add(uid)
                visited.add(p)

                # порядок: сначала офис
                a, b = (uid, p)
                if str(by_uid[a]["location"]) != "office" and str(by_uid[b]["location"]) == "office":
                    a, b = b, a

                mark = color_by_uid.get(uid) or color_by_uid.get(p) or "🔷"
                block = []
                for u in (a, b):
                    rr = by_uid[u]
                    block.append(f"{mark} {_display(u, {'full_name': (rr.get('full_name') or '').strip(), 'username': (rr.get('username') or '').strip()})} → {_loc_emoji(str(rr['location']))}")
                (pair_blocks_with_office if _block_has_office(block) else pair_blocks_without_office).append(block)
            else:
                visited.add(uid)
                singles.append(f"♦️ {_display(uid, {'full_name': (r.get('full_name') or '').strip(), 'username': (r.get('username') or '').strip()})} → {_loc_emoji(loc)}")

        for block in pair_blocks_with_office + pair_blocks_without_office:
            for line in block:
                lines.append(line)
        for line in singles:
            lines.append(line)

    # «Хвост» со справкой по командам для локаций — как в admin_users
    footer = (HELP_LOCATION_SHORT or "").strip()
    if footer:
        lines.append("")
        lines.append(footer)
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ===================== /loc_assign_manual =====================

def _parse_iso_date_or_none(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _resolve_user_ref(ref: str) -> tuple[int | None, str]:
    """
    Поддерживает:
      - числовой user_id
      - @username / username
    Возвращает (user_id, красивый ярлык для ответа).
    """
    s = (ref or "").strip()
    if not s:
        return (None, "")
    if s.isdigit():
        uid = int(s)
        try:
            prof = None
            for meth in ("get_user_by_id", "get_user", "get"):
                fn = getattr(user_repository, meth, None)
                if callable(fn):
                    prof = fn(uid)
                    if prof:
                        break
            label = f"ID {uid}"
            if prof:
                uname = (prof.get("username") or prof.get("tg_username") or "").strip()
                if uname:
                    label = f"@{uname}"
            return (uid, label)
        except Exception:
            return (uid, f"ID {uid}")

    uname = s[1:] if s.startswith("@") else s
    for meth in ("get_user_by_username", "find_by_username", "get_by_username"):
        fn = getattr(user_repository, meth, None)
        if callable(fn):
            u = fn(uname)
            if u:
                try:
                    return (int(u.get("user_id")), f"@{uname}")
                except Exception:
                    pass
    for meth in ("get_all_users", "list_all", "list_users"):
        fn = getattr(user_repository, meth, None)
        if callable(fn):
            for u in (fn() or []):
                name = (u.get("username") or u.get("tg_username") or "").strip()
                if name.lower() == uname.lower():
                    try:
                        return (int(u.get("user_id")), f"@{uname}")
                    except Exception:
                        pass
    return (None, s)


def _pick_upcoming_phase_kind(now: datetime) -> str:
    """
    «Предстоящая смена»:
    до 18:00 — day, после — night. Чтобы «сегодня» не попадать в хвост ночи со вчера.
    """
    return "day" if now.time() < _time(18, 0) else "night"


async def loc_assign_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_assign_manual <YYYY-MM-DD> <user_id|@username> [office|home] [group_key]
    /loc_assign_manual <user_id|@username> [office|home] [group_key]

    Перезаписывает назначение локации для пользователя на конкретную дату.
    Если дата опущена — берём сегодняшнюю дату и «предстоящую смену» (а не хвост ночной).
    Локация по умолчанию — office. Группа — или явно, или по членству.
    """
    # Только для админов
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return

    args = [a for a in (context.args or []) if a.strip()]
    if len(args) < 1:
        await update.message.reply_text(
            "Формат:\n"
            "/loc_assign_manual <YYYY-MM-DD> <user_id|@username> [office|home] [group_key]\n"
            "или\n"
            "/loc_assign_manual <user_id|@username> [office|home] [group_key]"
        )
        return

    # Разбор: дата опциональна
    d = _parse_iso_date_or_none(args[0])
    arg_idx = 0
    if d is not None:
        arg_idx = 1
        if len(args) <= 1:
            await update.message.reply_text("Укажи пользователя: user_id или @username.")
            return
    else:
        d = date.today()

    uid, label = _resolve_user_ref(args[arg_idx])
    if not uid:
        await update.message.reply_text("Не распознал пользователя. Укажи user_id или @username.")
        return

    # Локация и группа
    loc = None
    gk = None
    for token in args[arg_idx + 1:]:
        t = token.lower()
        if t in ("office", "офис", "🏢"):
            loc = "office"
        elif t in ("home", "дом", "remote", "🏠"):
            loc = "home"
        else:
            gk = gk or token

    if not loc:
        loc = "office"
    if not gk:
        gk = _find_user_time_group_key(uid)
        if not gk:
            await update.message.reply_text("Не смог определить группу пользователя. Укажи <group_key> явно.")
            return

    # Предстоящая смена, если сегодня
    phase_kind = "day"
    if d == date.today():
        phase_kind = _pick_upcoming_phase_kind(datetime.now())

    # Запись через repository (несколько возможных имён методов для совместимости)
    if not loc_repo:
        await update.message.reply_text(
            "ℹ️ В этом билде нет location_repository для ручной записи. "
            f"Проверь план: /loc_next {escape(gk)}"
        )
        return

    ok = False
    for meth in ("upsert_manual", "upsert_assignment", "assign_manual"):
        fn = getattr(loc_repo, meth, None)
        if callable(fn):
            try:
                res = fn(str(gk), d, int(uid), str(loc), str(phase_kind))
                ok = bool(res) if res is not None else True
                break
            except Exception:
                continue

    if not ok:
        await update.message.reply_text(
            "❌ Не удалось записать назначение (нет подходящего метода в location_repository)."
        )
        return

    await update.message.reply_text(
        f"✅ Перезаписано: <b>{escape(label)}</b> — {escape(loc)} на {d} ({phase_kind}).\n"
        f"Проверь: /loc_next {escape(gk)}",
        parse_mode=ParseMode.HTML,
    )

async def loc_probe(update, context):
    # /loc_probe vrn3   → если аргумента нет, подставь свою дефолт-группу
    group_key = (context.args[0].strip() if context.args else "vrn3")
    rows = get_group_locations_today(group_key)

    if not rows:
        await update.effective_message.reply_text(f"loc_probe: пусто для {group_key} на сегодня.")
        return

    office_cnt = sum(1 for *_ , is_office in rows if is_office)
    lines = [f"loc_probe @{group_key} сегодня: {len(rows)} чел., офис: {office_cnt}"]
    for uid, username, loc, is_office in rows:
        mark = "🏢" if is_office else "🏠"
        at = f"@{username}" if username else str(uid)
        lines.append(f"• {at}: {mark} ({loc})")
    await update.effective_message.reply_text("\n".join(lines)[:4096])

# регистрируем хендлер (там, где у тебя Application/dispatcher):
# application.add_handler(CommandHandler("loc_probe", loc_probe))
async def loc_probe_exec(update, context):
    today = datetime.now(MSK).date()
    # Берём тех же, кого ты считаешь «exec candidates».
    # Если ты уже сохраняешь список последних кандидатов – используем его:
    exec_ids = [int(c.user_id) for c in context.bot_data.get("last_exec_candidates", [])] \
               or [u for u,_,_ in context.bot_data.get("last_exec_rows", [])]  # запасной вариант
    locmap = get_location_map_for_users_on(today, exec_ids)
    lines = [f"loc_probe_exec @ {today}: {len(exec_ids)}"]
    for uid in exec_ids:
        lines.append(f"• {uid}: {locmap.get(uid, 'home')}")
    await update.effective_message.reply_text("\n".join(lines)[:4096])