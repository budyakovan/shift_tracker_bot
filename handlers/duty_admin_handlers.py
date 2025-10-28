# /home/telegrambot/shift_tracker_bot/handlers/duty_admin_handlers.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, Optional, List
import logging, re
from datetime import datetime, date
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from html import escape

from database import time_repository as time_repo
from database.duty_repository import (
    # RR / по времени
    auto_assign_for_date,                 # fair-load по дате (fallback)
    auto_assign_for_date_rr,              # RR по дате (если реализовано)
    auto_assign_for_datetime_rr,          # RR «на сейчас»
    get_on_duty_members_now,
    get_on_duty_members_now_debug,
    get_assignments,
    # Взвешенное распределение (assignw*)
    plan_duties_now_weighted,             # план «на сейчас» без записи
    auto_assign_weighted_for_date,        # запись на дату
    auto_assign_weighted_global_now,      # запись «на сейчас» (глобально)
    reconcile_weighted_global_now,        # сверка назначений «на сейчас»
)

from database.duty_admin_repository import (
    set_member_rank, list_member_ranks,
    add_exclusion, remove_exclusion,
    get_member_rank, reset_assignments_for_date,
)

import database.users_repository as user_repository

logger = logging.getLogger(__name__)

MAX_TG_CHARS = 3800

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

def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def _name_from_member(m: dict) -> str:
    fn = (m.get("first_name") or "").strip()
    ln = (m.get("last_name") or "").strip()
    nm = f"{fn} {ln}".strip()
    if nm:
        return nm
    u = (m.get("username") or "").strip()
    return f"@{u}" if u else str(m.get("user_id"))

# ---------- RANK ----------

async def rank_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rank_set <group_key> <user_id> <rank>
    rank: 1-лидер, 2-специалист, 3-младший
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        await update.message.reply_text("Формат: /rank_set <group_key> <user_id> <1|2|3>")
        return
    gk, user_id, rank = args[0], int(args[1]), int(args[2])
    if rank not in (1, 2, 3):
        await update.message.reply_text("Ранг должен быть 1, 2 или 3.")
        return
    ok = set_member_rank(gk, user_id, rank, uid)
    await update.message.reply_text("✅ Сохранено." if ok else "❌ Не удалось.")

async def rank_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rank_list <group_key>
    """
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Формат: /rank_list <group_key>")
        return
    gk = args[0]
    rows = list_member_ranks(gk)
    if not rows:
        await update.message.reply_text("Пока нет записей.")
        return
    lines = [f"Ранги по группе <b>{escape(gk)}</b>:"]
    for r in rows:
        lines.append(f"• {r['user_id']} → {r['rank']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

# ---------- EXCLUSIONS (список удалён по задаче) ----------

async def duty_exclude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duty_exclude <user_id> <YYYY-MM-DD> <YYYY-MM-DD> [group_key] [reason...]
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /duty_exclude <user_id> <YYYY-MM-DD> <YYYY-MM-DD> [group_key] [reason]")
        return
    try:
        user_id = int(args[0])
        d1 = _d(args[1]); d2 = _d(args[2])
        gk = None; reason = None
        if len(args) >= 4 and not re.match(r"^\d{4}-\d{2}-\d{2}$", args[3]):
            gk = args[3]
        if len(args) >= 5:
            reason = " ".join(args[4:])
        new_id = add_exclusion(user_id, d1, d2, gk, reason, uid)
        await update.message.reply_text(f"✅ Исключение создано: #{new_id}")
    except Exception:
        await update.message.reply_text("❌ Ошибка парсинга. Формат дат YYYY-MM-DD.")

async def duty_exclude_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duty_exclude_del <id>
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Формат: /duty_exclude_del <id>")
        return
    ok = remove_exclusion(int(args[0]))
    await update.message.reply_text("🗑 Удалено." if ok else "❌ Не удалось удалить.")

# ---------- RR/Дата/Сейчас ----------

async def assign_duties_rr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /assign_duties_rr [YYYY-MM-DD] [group_key]
    Если RR недоступен, используем auto_assign_for_date (fair-load).
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        on_date = _d(args[0])
        gk = args[1] if len(args) > 1 else None
    else:
        on_date = date.today()
        gk = args[0] if args else None

    try:
        cnt = auto_assign_for_date_rr(on_date, author_id=uid, group_key=gk)
    except Exception:
        logger.exception("assign_duties_rr: fallback to fair-load")
        cnt = auto_assign_for_date(on_date, author_id=uid, group_key=gk)
    await update.message.reply_text(f"✅ Назначено: {cnt} (дата {on_date}, группа {gk or 'ALL'}).")

async def assign_duties_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /assign_duties_now [group_key]
    RR-распределение «на сейчас» с учётом временных окон.
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    gk = args[0] if args else None
    now_local = datetime.now(ZoneInfo("Europe/Moscow"))
    try:
        cnt = auto_assign_for_datetime_rr(now_local, author_id=uid, group_key=gk)
    except Exception:
        logger.exception("assign_duties_now failed")
        cnt = 0
    await update.message.reply_text(
        f"✅ RR-назначено на сейчас: {cnt} (в {now_local:%Y-%m-%d %H:%M}, группа {gk or 'ALL'})."
    )

# ---------- «Кто сейчас» / «Дежурства сейчас» ----------

async def who_on_shift_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /who_on_shift_now [group_key]
    👤Имя 🔗 @user Группа <code>vrn1</code> Ранг <code>2</code>
    """
    args = context.args or []
    gk_filter = args[0] if args else None
    now_local = datetime.now(ZoneInfo("Europe/Moscow"))

    groups = time_repo.list_groups() or []
    if gk_filter:
        groups = [g for g in groups if str(g.get("key")) == str(gk_filter)]

    active: list[dict] = []
    for g in groups:
        gkey = str(g.get("key"))
        members = get_on_duty_members_now(gkey, now_local)
        if not members:
            continue
        for m in members:
            uid = int(m.get("user_id"))
            try:
                rank_val = get_member_rank(gkey, uid)
            except Exception:
                rank_val = None
            rank_str = str(rank_val) if rank_val in (1, 2, 3) else "?"
            active.append({
                "name": _name_from_member(m),
                "username": (m.get("username") or "").strip(),
                "group_key": gkey,
                "rank": rank_str,
            })

    if not active:
        await update.message.reply_text("Сейчас никто не в смене.")
        return

    active.sort(key=lambda a: (a["group_key"].lower(), a["rank"], a["name"].lower()))
    lines: list[str] = [
        f"🕒 Сейчас: {now_local:%Y-%m-%d %H:%M} (Москва)",
        "Активные сотрудники:",
    ]
    for a in active:
        uname_fmt = f" 🔗 @{escape(a['username'])}" if a['username'] else ""
        lines.append(
            f"👤{escape(a['name'])}{uname_fmt} Группа <code>{escape(a['group_key'])}</code> "
            f"Ранг <code>{escape(a['rank'])}</code>"
        )
    await _reply_chunked(update, "\n".join(lines), parse_mode=ParseMode.HTML)

async def who_on_shift_now_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /who_on_shift_now_debug [group_key]
    Показывает активных и пропущенных с причинами.
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return

    args = context.args or []
    gk_filter = args[0] if args else None
    now_local = datetime.now(ZoneInfo("Europe/Moscow"))

    groups = time_repo.list_groups() or []
    if gk_filter:
        groups = [g for g in groups if str(g.get("key")) == str(gk_filter)]
    if not groups:
        await update.message.reply_text("Группы не найдены.")
        return

    lines: list[str] = [f"🕒 Сейчас: {now_local:%Y-%m-%d %H:%M} (Москва)"]
    any_active = False

    for g in groups:
        gkey = str(g.get("key"))
        dbg = get_on_duty_members_now_debug(gkey, now_local)
        ok = dbg.get("ok") or []
        skipped = dbg.get("skipped") or []

        if ok:
            if not any_active:
                lines.append("Активные сотрудники:")
                any_active = True
            for m in ok:
                nm = _name_from_member(m)
                lines.append(f"👤{escape(nm)} Группа <code>{escape(gkey)}</code>")

        if skipped:
            lines.append(f"— Пропущены в <code>{escape(gkey)}</code> —")
            for s in skipped:
                nm = escape(s.get("name") or str(s.get("user_id")))
                rs = escape(str(s.get("reason") or ""))
                lines.append(f"  • {nm}: {rs}")

    if not any_active:
        lines.append("Сейчас никто не в смене.")
    await _reply_chunked(update, "\n".join(lines), parse_mode=ParseMode.HTML)

async def duties_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duties_now [group_key]
    Показать, кто сейчас в смене и какие у них назначения на сегодня.
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

# ---------- RESET на дату ----------

async def duties_reset_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duties_reset_today [group_key]
    Удалить назначения из duty_assignments за сегодня (или за указанную дату).
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return

    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        on_date = _d(args[0])
        gk = args[1] if len(args) > 1 else None
    else:
        on_date = datetime.now(ZoneInfo("Europe/Moscow")).date()
        gk = args[0] if args else None

    deleted = reset_assignments_for_date(on_date, gk)
    await update.message.reply_text(f"🗑 Сброшено назначений за {on_date} (группа {gk or 'ALL'}): {deleted}.")

# ---------- ВЗВЕШЕННОЕ НАЗНАЧЕНИЕ (assignw*) ----------

async def assignw_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /assignw_now
    Глобальное взвешенное назначение «на сейчас» по активным сотрудникам.
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    now_local = datetime.now(ZoneInfo("Europe/Moscow"))
    try:
        cnt = auto_assign_weighted_global_now(now_local, author_id=uid)
    except Exception:
        logger.exception("assignw_now failed")
        cnt = 0
    await update.message.reply_text(f"✅ Глобальное весовое назначение на сейчас: {cnt} (в {now_local:%Y-%m-%d %H:%M}).")

async def assignw_recon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Перерасстановка «на сейчас» при изменении состава / AFK.
    Поддерживает режимы:
      /assignw_recon                -> SOFT
      /assignw_recon family         -> FAMILY
      /assignw_recon group          -> GROUP
      /assignw_recon vrn3 123456789 -> для конкретной группы и user_id
    """
    args = context.args or []
    mode = None
    group_key = None
    afk_user_id = None

    for a in args:
        a_low = a.lower()
        if a_low in ("soft","family","group"):
            mode = a_low.upper()
        elif a.isdigit():
            afk_user_id = int(a)
        else:
            group_key = a

    # Если группа не указана — попробуем определить по умолчанию (например, из настроек).
    if not group_key:
        group_key = getattr(config, "DEFAULT_GROUP_KEY", None)

    if not group_key:
        await update.message.reply_text("❗ Укажи group_key (например, vrn3) или настрой DEFAULT_GROUP_KEY в config.py")
        return

    # Если user_id не задан — это «общий» рекон: можно пробежаться по списку AFK сейчас.
    if afk_user_id is None:
        # У тебя может быть функция get_afk_active(); тут оставим заглушку.
        await update.message.reply_text("ℹ️ Режим без user_id: пока поддержан только точечный AFK.\nПример: /assignw_recon vrn3 123456789 family")
        return

    res = recon_repo.recon_on_afk(user_id=afk_user_id, group_key=group_key, now_local=datetime.now(MSK), mode=mode)
    text = [
        f"🔁 Реконфигурация (mode={mode or config.FAMILY_RECON_DEFAULT_MODE}) для группы <b>{group_key}</b>, user=<code>{afk_user_id}</code>",
        f"kept={res['kept']}, reassigned={res['reassigned']}, degraded={res['degraded']}, skipped={res['skipped']}",
        "",
        "<b>Детали:</b>"
    ]
    for d in res["details"]:
        text.append(f"• {d}")

    await update.message.reply_text("\n".join(text), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def assignw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /assignw <YYYY-MM-DD> [group_key]
    Взвешенное назначение на дату.
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Формат: /assignw <YYYY-MM-DD> [group_key]")
        return
    try:
        on_date = _d(args[0])
    except Exception:
        await update.message.reply_text("Дата в формате YYYY-MM-DD.")
        return
    gk = args[1] if len(args) > 1 else None

    try:
        cnt = auto_assign_weighted_for_date(on_date, author_id=uid, group_key=gk)
    except Exception:
        logger.exception("assignw failed")
        cnt = 0
    await update.message.reply_text(f"✅ Весовое назначение на {on_date}: {cnt} (группа {gk or 'ALL'}).")
