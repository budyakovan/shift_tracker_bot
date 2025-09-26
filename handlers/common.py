from datetime import date, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from services.user_manager import user_manager
from services.auth_manager import auth_manager
from utils.formatters import format_shift_message


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальный обработчик текстовых сообщений:
    - проверяет одобрение пользователя
    - понимает быстрые кнопки "Сегодня"/"Завтра"
    - на прочий текст даёт короткую подсказку
    """
    if not update.message or not update.message.text:
        return

    text = (update.message.text or "").strip().lower()
    user_id = update.effective_user.id
    if text in ("❓ помощь", "помощь", "? помощь", "/help", "help"):
        # импортируем локально, чтобы избежать циклических импортов
        from handlers.help_handlers import help_command as _help
        await _help(update, context)
        return

    # Проверяем, approved ли пользователь
    if not auth_manager.is_user_approved(user_id):
        await update.message.reply_text(
            "❌ Ваш аккаунт ожидает одобрения администратора.\n\n"
            f"🆔 Ваш ID: {user_id}\n"
            "📋 Передайте этот ID администратору для активации."
        )
        return

    # Быстрые кнопки
    if text in ("📅 сегодня", "сегодня", "/today"):
        await handle_today(update, user_id)
        return

    if text in ("📅 завтра", "завтра", "/tomorrow"):
        await handle_tomorrow(update, user_id)
        return

    # По умолчанию — короткая подсказка
    await update.message.reply_text(
        "Не понял запрос. Доступно: /today, /tomorrow, /help",
    )


async def handle_today(update: Update, user_id: int):
    """Смена на сегодня"""
    today = date.today()
    shift_info = user_manager.get_user_shift(user_id, today)
    if shift_info:
        message = format_shift_message(shift_info)
        await update.message.reply_text(message, parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Не удалось получить данные о смене на сегодня")


async def handle_tomorrow(update: Update, user_id: int):
    """Смена на завтра"""
    tomorrow = date.today() + timedelta(days=1)
    shift_info = user_manager.get_user_shift(user_id, tomorrow)
    if shift_info:
        message = format_shift_message(shift_info)
        await update.message.reply_text(message, parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Не удалось получить данные о смене на завтра")


async def my_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать пользователю его ID (если где-то используется)"""
    user = update.effective_user
    user_id = user.id
    username = user.username or "не установлен"
    first_name = user.first_name or ""
    last_name = user.last_name or ""

    message = (
        f"👤 <b>Ваша информация:</b>\n\n"
        f"🆔 <b>Ваш ID:</b> <code>{user_id}</code>\n"
        f"📛 <b>Имя:</b> {first_name} {last_name}\n"
        f"🔗 <b>Username:</b> @{username}\n\n"
        f"💡 <b>Этот ID нужен для:</b>\n"
        f"• Одобрения аккаунта администратором\n"
        f"• Технической поддержки\n"
        f"• Идентификации в системе"
    )

    await update.message.reply_text(message, parse_mode='HTML')
