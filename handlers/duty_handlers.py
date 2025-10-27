# /home/telegrambot/shift_tracker_bot/handlers/duty_handlers.py
# -*- coding: utf-8 -*-
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from html import escape
from zoneinfo import ZoneInfo
from database import time_repository as time_repo

from database.duty_repository import (
    auto_assign_for_date,     # используется в assign_duties
    get_on_duty_members_now,  # используется в duties_now
    get_assignments,          # используется в my_duties*, duties_all
)

import database.users_repository as user_repository

logger = logging.getLogger(__name__)

MAX_TG_CHARS = 3800  # запас от лимита Телеграма

async def _reply_chunked(update: Update, text: str, parse_mode: Optional[str] = None):
    if not text:
        await update.message.reply_text("Пусто.", parse_mode=parse_mode)
        return
    start = 0
    n = len(text)
    while start < n:
        end = start + MAX_TG_CHARS
        if end < n:
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl
        await update.message.reply_text(text[start:end], parse_mode=parse_mode)
        start = end

def _is_admin(user_id: int) -> bool:
    ur = user_repository
    if hasattr(ur, "is_user_admin"):
        try:
            return bool(ur.is_user_admin(user_id))
        except Exception:
            pass
    roles = []
    if hasattr(ur, "get_user_roles"):
        try:
            roles = ur.get_user_roles(user_id) or []
        except Exception:
            roles = []
    roles_lower = {str(r).strip().lower() for r in roles}
    return ("admin" in roles_lower)

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def _parse_ondate(args) -> date:
    if not args:
        return date.today()
    s = " ".join(args).strip().lower()
    if s in ("today", "сегодня"):
        return date.today()
    if s in ("tomorrow", "завтра"):
        return date.today() + timedelta(days=1)
    try:
        parts = s.split(".")
        if len(parts) >= 2:
            d = int(parts[0]); m = int(parts[1])
            y = int(parts[2]) if len(parts) >= 3 else date.today().year
            return date(y, m, d)
    except Exception:
        pass
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return date.today()

# ===== Admin: авто-назначение по дате (оставлено) =====

async def assign_duties(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /assign_duties [YYYY-MM-DD] [group_key]
    Авто-распределение обязанностей на дату (или на сегодня).
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return

    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        on_date = _parse_date(args[0])
        gkey = args[1] if len(args) > 1 else None
    else:
        on_date = date.today()
        gkey = args[0] if args else None

    count = auto_assign_for_date(on_date, author_id=uid, group_key=gkey)
    await update.message.reply_text(
        f"✅ Назначено {count} обязанностей на {on_date}" + (f" (группа {gkey})" if gkey else "")
    )

# ===== Пользовательские команды (оставлены) =====

async def my_duties(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /my_duties [дата|'today'|'tomorrow'|'сегодня'|'завтра'|DD.MM[.YYYY]|YYYY-MM-DD]
    """
    on_date = _parse_ondate(context.args)
    uid = update.effective_user.id
    rows = get_assignments(on_date)
    mine = [r for r in rows if int(r["user_id"]) == int(uid)]
    if not mine:
        await update.message.reply_text(f"У вас нет назначенных обязанностей на {on_date:%Y-%m-%d}.")
        return
    lines = [f"🗓 {on_date:%A}, {on_date:%Y-%m-%d}"]
    for r in mine:
        lines.append(f"• {escape(r['title'])} — группа <b>{escape(r['group_key'])}</b>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def my_duties_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /my_duties_next — ближайший будущий день с назначенными обязанностями
    """
    uid = update.effective_user.id
    start = date.today()
    horizon = 30
    for i in range(horizon + 1):
        day = start + timedelta(days=i)
        mine = [r for r in get_assignments(day) if int(r["user_id"]) == int(uid)]
        if mine:
            lines = [f"🗓 {day:%A}, {day:%Y-%m-%d} — ближайшие ваши обязанности:"]
            for r in mine:
                lines.append(f"• {escape(r['title'])} — группа <b>{escape(r['group_key'])}</b>")
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
            return
    await update.message.reply_text("В ближайшие 30 дней ваших назначений не нашлось.")

async def duties_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duties_now [group_key]
    Показывает обязанности СЕЙЧАС, сгруппированные по сотрудникам внутри каждой группы.
    Внизу выводит список групп, где никто не в смене.
    """
    args = context.args or []
    gk_filter = args[0] if args else None

    now_local = datetime.now(ZoneInfo("Europe/Moscow"))
    today = now_local.date()

    groups = time_repo.list_groups() or []
    if gk_filter:
        groups = [g for g in groups if str(g.get("key")) == str(gk_filter)]

    if not groups:
        await update.message.reply_text("Группы не найдены.")
        return

    def _name_from_member(m: dict) -> str:
        fn = (m.get("first_name") or "").strip()
        ln = (m.get("last_name") or "").strip()
        nm = f"{fn} {ln}".strip()
        if nm:
            return nm
        u = (m.get("username") or "").strip()
        return f"@{u}" if u else str(m.get("user_id"))

    lines: list[str] = [f"🕒 Сейчас: {now_local:%Y-%m-%d %H:%M} (Москва)"]
    empty_groups: list[str] = []

    for g in groups:
        gkey = str(g.get("key"))
        members = get_on_duty_members_now(gkey, now_local)

        if not members:
            empty_groups.append(gkey)
            continue

        lines.append(f"\n<b>Группа {escape(gkey)}</b>")

        assigns = get_assignments(today, gkey)
        by_user: Dict[int, List[str]] = {}
        for a in assigns:
            by_user.setdefault(int(a["user_id"]), []).append(str(a["title"]))

        for m in members:
            uid = int(m.get("user_id"))
            nm = _name_from_member(m)
            duties_list = by_user.get(uid, [])
            if duties_list:
                duties_str = "; ".join(escape(t) for t in duties_list)
                lines.append(f"👤 {escape(nm)} — {duties_str}")
            else:
                lines.append(f"👤 {escape(nm)} — (без назначений)")

    if empty_groups:
        lines.append("\nГруппы без смены сейчас: " + ", ".join(f"<code>{escape(k)}</code>" for k in empty_groups))

    await _reply_chunked(update, "\n".join(lines), parse_mode=ParseMode.HTML)

# ===== Совокупный список назначений на дату (совместимость с main.py) =====

async def duties_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duties_all [YYYY-MM-DD] [group_key]
    Выводит все назначения на дату, сгруппировано по пользователям внутри группы.
    """
    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        on_date = _parse_date(args[0])
        gkey = args[1] if len(args) > 1 else None
    else:
        on_date = date.today()
        gkey = args[0] if args else None

    rows = get_assignments(on_date, gkey)
    if not rows:
        await update.message.reply_text(f"Назначений нет на {on_date:%Y-%m-%d}.")
        return

    # group_key -> user_id -> [titles]
    grouped: Dict[str, Dict[int, List[str]]] = {}
    for r in rows:
        g = str(r["group_key"])
        uid = int(r["user_id"])
        grouped.setdefault(g, {}).setdefault(uid, []).append(str(r["title"]))

    # простой способ получить имя пользователя — через текущие группы
    members_idx: Dict[int, str] = {}
    for g in (time_repo.list_groups() or []):
        info = time_repo.get_group_info(str(g.get("key")))
        for m in (info or {}).get("members", []):
            uid = int(m.get("user_id"))
            fn = (m.get("first_name") or "").strip()
            ln = (m.get("last_name") or "").strip()
            nm = (f"{fn} {ln}".strip() or (("@" + (m.get("username") or "").strip()) if m.get("username") else str(uid)))
            if uid not in members_idx:
                members_idx[uid] = nm

    lines: List[str] = [f"🗓 {on_date:%A}, {on_date:%Y-%m-%d} — назначения по сотрудникам"]
    for g, by_user in grouped.items():
        lines.append(f"\n<b>{escape(g)}</b>:")
        for uid, titles in sorted(by_user.items(), key=lambda kv: members_idx.get(kv[0], str(kv[0])).lower()):
            nm = members_idx.get(uid, str(uid))
            tl = "; ".join(escape(t) for t in titles)
            lines.append(f"• {escape(nm)}: {tl}")

    await _reply_chunked(update, "\n".join(lines), parse_mode=ParseMode.HTML)

# === УДАЛЁННЫЕ КОМАНДЫ (по задаче) ===
# duty_add         — удалено
# duties_list      — удалено
# duty_update      — удалено
# duty_delete      — удалено
# duties_today     — удалено
# duty_exclude_list — удалено (была в другом файле)
