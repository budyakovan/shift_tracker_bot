# -*- coding: utf-8 -*-
import logging
from telegram import Update
from telegram.ext import ContextTypes

from handlers.help_texts import (
    HELP_MAIN_FULL,
    HELP_MAIN_SHORT,
    HELP_USERS_FULL,
    HELP_USERS_SHORT,
    HELP_GROUPS_FULL,
    HELP_GROUPS_SHORT,
    HELP_TIME_PROFILES_FULL,
    HELP_TIME_PROFILES_SHORT,
    HELP_VACATIONS_FULL,
    HELP_VACATIONS_SHORT,
    HELP_SICK_FULL,
    HELP_SICK_SHORT,
    HELP_ADMIN_ALL_FULL,
    HELP_DUTIES_SHORT,
    HELP_DUTIES_FULL,
)

logger = logging.getLogger(__name__)

# ---------- ОБРАБОТЧИКИ КОМАНД ----------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MAIN_SHORT, parse_mode="HTML")

async def help_full_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MAIN_FULL, parse_mode="HTML")

# users
async def help_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_USERS_FULL, parse_mode="HTML")

async def help_users_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_USERS_SHORT, parse_mode="HTML")

# groups
async def help_groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_GROUPS_FULL, parse_mode="HTML")

async def help_groups_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_GROUPS_SHORT, parse_mode="HTML")

# time profiles
async def help_time_profiles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TIME_PROFILES_FULL, parse_mode="HTML")

async def help_time_profiles_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TIME_PROFILES_SHORT, parse_mode="HTML")

# vacations
async def help_vacations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_VACATIONS_FULL, parse_mode="HTML")

async def help_vacations_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_VACATIONS_SHORT, parse_mode="HTML")

# sick
async def help_sick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_SICK_FULL, parse_mode="HTML")

async def help_sick_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_SICK_SHORT, parse_mode="HTML")

# admin all
async def help_admin_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_ADMIN_ALL_FULL, parse_mode="HTML")

async def help_duties_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_DUTIES_FULL, parse_mode="HTML")

async def help_duties_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_DUTIES_SHORT, parse_mode="HTML")
