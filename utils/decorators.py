# utils/decorators.py
# -*- coding: utf-8 -*-
import functools
import logging
from typing import Callable, Any, Awaitable

from database.connection import db_connection
from services.auth_manager import auth_manager  # единый источник прав

logger = logging.getLogger(__name__)

async def _is_user_approved(user_id: int) -> bool:
    try:
        conn = db_connection.get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='users' AND column_name='is_approved'
                LIMIT 1
            """)
            if cur.fetchone() is None:
                return True
            cur.execute("SELECT is_approved FROM users WHERE user_id=%s LIMIT 1", (user_id,))
            row = cur.fetchone()
            return bool(row and row[0])
    except Exception as e:
        logger.error("approved check failed: %s", e)
        return True

def require_admin(func: Callable[..., Awaitable[Any]]):
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        uid = update.effective_user.id if update and update.effective_user else None
        try:
            if uid is None or not auth_manager.is_admin(uid):
                await update.message.reply_text(
                    "❌ Недостаточно прав для выполнения этой команды.\nОбратитесь к администратору."
                )
                return
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.exception("require_admin wrapper error: %s", e)
            await update.message.reply_text("⚠️ Внутренняя ошибка при выполнении команды.")
    return wrapper

def require_approved(func: Callable[..., Awaitable[Any]]):
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        uid = update.effective_user.id if update and update.effective_user else None
        try:
            if uid is None:
                await update.message.reply_text("❌ Не удалось определить пользователя.")
                return
            if auth_manager.is_admin(uid):
                return await func(update, context, *args, **kwargs)
            if not await _is_user_approved(uid):
                await update.message.reply_text("⏳ Ваш аккаунт ещё не одобрен.")
                return
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.exception("require_approved wrapper error: %s", e)
            await update.message.reply_text("⚠️ Внутренняя ошибка при выполнении команды.")
    return wrapper
