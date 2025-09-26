# /home/telegrambot/shift_tracker_bot/handlers/location_handlers.py
# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from html import escape

from database.repository import UserRepository
from database.location_repository import assign_locations_for_group, get_locations, office_report
from database import time_repository as time_repo

def _is_admin(uid: int) -> bool:
    ur = UserRepository()
    try:
        return bool(getattr(ur, "is_user_admin")(uid))
    except Exception:
        return False

def _parse_date(s: str) -> date | None:
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except: return None

async def loc_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_assign <YYYY-MM-DD> <group_key>
    Назначает офис/дом по правилам.
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Формат: /loc_assign <YYYY-MM-DD> <group_key>")
        return
    d = _parse_date(args[0])
    g = args[1]
    if not d:
        await update.message.reply_text("Дата в формате YYYY-MM-DD.")
        return
    cnt = assign_locations_for_group(g, d)
    await update.message.reply_text(f"✅ Назначено {cnt} записей для {g} на {d}.")

async def loc_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_today [YYYY-MM-DD] [group_key]
    """
    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        d = _parse_date(args[0])
        g = args[1] if len(args) > 1 else None
    else:
        d = date.today()
        g = args[0] if args else None
    rows = get_locations(d, g)
    if not rows:
        await update.message.reply_text("Назначений нет.")
        return
    lines = [f"🗓 <b>{d.strftime('%Y-%m-%d')}</b>"]
    for r in rows:
        lines.append(f"• <b>{escape(r['group_key'])}</b> — {r['user_id']} → {'🏢 Офис' if r['location']=='office' else '🏠 Дом'}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def loc_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /loc_report <group_key> <YYYY-MM-01> <YYYY-MM-31>
    Свод по офис-дням за период.
    """
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /loc_report <group_key> <date_from> <date_to>")
        return
    g = args[0]
    d1 = _parse_date(args[1]); d2 = _parse_date(args[2])
    if not d1 or not d2:
        await update.message.reply_text("Даты в формате YYYY-MM-DD.")
        return
    rows = office_report(g, d1, d2)
    if not rows:
        await update.message.reply_text("Данных нет.")
        return
    lines = [f"📊 <b>{escape(g)}</b> — офис-дни за {d1}…{d2}"]
    for r in rows:
        lines.append(f"• {r['user_id']}: {r['office_days']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
