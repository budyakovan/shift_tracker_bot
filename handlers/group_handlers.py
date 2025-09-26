# -*- coding: utf-8 -*-
import logging
from telegram import Update
from telegram.ext import ContextTypes

from database import group_repository

logger = logging.getLogger(__name__)

async def mygroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    grp = group_repository.get_user_group(user_id)
    if not grp:
        await update.message.reply_text("🪪 Твоя группа не назначена.")
        return
    epoch_text = grp["epoch"].strftime("%d.%m.%Y") if grp["epoch"] else f"BASE+{grp['offset_days']}д"
    await update.message.reply_text(
        f"👥 <b>Твоя группа</b>\n"
        f"Ключ: <code>{grp['key']}</code>\n"
        f"Название: {grp['name']}\n"
        f"Сдвиг: {grp['offset_days']} дн.\n"
        f"Эпоха: {epoch_text}",
        parse_mode="HTML",
    )

async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    groups = group_repository.list_groups()
    if not groups:
        await update.message.reply_text("Список групп пуст. Попроси администратора создать группы.")
        return
    lines = ["📚 <b>Доступные группы</b>:\n"]
    for g in groups:
        epoch_text = g["epoch"].strftime("%d.%m.%Y") if g["epoch"] else f"BASE+{g['offset_days']}д"
        lines.append(f"• <code>{g['key']}</code> — {g['name']} (сдвиг {g['offset_days']} дн., эпоха: {epoch_text})")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
