# /home/telegrambot/shift_tracker_bot/handlers/help_handlers.py
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
    HELP_DUTIES_SHORT,
    HELP_DUTIES_FULL,
    HELP_LOCATION_FULL,
    HELP_LOCATION_SHORT,
    HELP_RANK_ROTATION_FULL,
    HELP_RANK_ROTATION_SHORT,
    HELP_RANK_FULL,
    HELP_RANK_SHORT,
    HELP_HOLIDAYS_FULL,
    HELP_HOLIDAYS_SHORT,
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


async def help_duties_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_DUTIES_FULL, parse_mode="HTML")

async def help_duties_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_DUTIES_SHORT, parse_mode="HTML")

# location
async def help_location_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_LOCATION_FULL, parse_mode="HTML")

async def help_location_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_LOCATION_SHORT, parse_mode="HTML")

async def help_rank_rotation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_RANK_ROTATION_FULL, parse_mode="HTML")

async def help_rank_rotation_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_RANK_ROTATION_SHORT, parse_mode="HTML")

async def help_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_RANK_FULL, parse_mode="HTML")

async def help_rank_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_RANK_SHORT, parse_mode="HTML")

async def help_holidays_command(update, context):
    await update.message.reply_text(HELP_HOLIDAYS_FULL, parse_mode="HTML")

async def help_holidays_short_command(update, context):
    await update.message.reply_text(HELP_HOLIDAYS_SHORT, parse_mode="HTML")
