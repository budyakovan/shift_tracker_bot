# -*- coding: utf-8 -*-
import logging, re
from datetime import datetime, date
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database.duty_admin_repository import (
    set_member_rank, list_member_ranks,
    add_exclusion, remove_exclusion, list_exclusions
)
from database.duty_repository import auto_assign_for_date_rr, get_assignments
from database.repository import UserRepository, USER_ROLE_ADMIN
from html import escape

logger = logging.getLogger(__name__)

def _is_admin(user_id: int) -> bool:
    ur = UserRepository()
    # Надёжная проверка по БД (без чувствительности к регистру)
    if hasattr(ur, "is_user_admin"):
        try:
            return bool(ur.is_user_admin(user_id))
        except Exception:
            pass

    # Fallback: если где-то всё ещё используют get_user_roles/константу
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

# ===== RANK =====
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
    if rank not in (1,2,3):
        await update.message.reply_text("Ранг должен быть 1,2 или 3.")
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

# ===== EXCLUSIONS =====
async def duty_exclude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duty_exclude <user_id> <YYYY-MM-DD> <YYYY-MM-DD> [group_key] [reason...]
    group_key можно не указывать (тогда исключение глобальное).
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
        if len(args) >= 4:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", args[3]):
                # это не group_key, а четвёртая дата — запретим
                await update.message.reply_text("Проверь формат: [group_key] идёт после дат.")
                return
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

async def duty_exclude_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duty_exclude_list [YYYY-MM-DD] [group_key] [user_id]
    """
    args = context.args or []
    on_date = _d(args[0]) if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]) else None
    gk = None; uid_f = None
    rest = args[1:] if on_date else args
    if rest:
        if rest[0].isdigit():
            uid_f = int(rest[0])
        else:
            gk = rest[0]
    if len(rest) >= 2 and rest[1].isdigit():
        uid_f = int(rest[1])

    rows = list_exclusions(on_date, gk, uid_f)
    if not rows:
        await update.message.reply_text("Нет исключений по заданным условиям.")
        return
    lines = []
    for r in rows:
        g = r['group_key'] or "ALL"
        rr = (f" — {r['reason']}" if r.get('reason') else "")
        lines.append(f"#{r['id']} {r['user_id']} [{g}] {r['date_from']}—{r['date_to']}{rr}")
    await update.message.reply_text("\n".join(lines))

# ===== RR ASSIGN =====
async def assign_duties_rr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /assign_duties_rr [YYYY-MM-DD] [group_key]
    Round-robin распределение (честное по очереди).
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        on_date = datetime.strptime(args[0], "%Y-%m-%d").date()
        gk = args[1] if len(args) > 1 else None
    else:
        on_date = date.today()
        gk = args[0] if args else None

    cnt = auto_assign_for_date_rr(on_date, author_id=uid, group_key=gk)
    await update.message.reply_text(f"✅ RR-назначено: {cnt} (дата {on_date}, группа {gk or 'ALL'}).")
