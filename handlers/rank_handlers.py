# /home/telegrambot/shift_tracker_bot/handlers/rank_handlers.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from html import escape


from database.rank_repository import (
    set_member_rank, list_member_ranks,

)


logger = logging.getLogger(__name__)


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


