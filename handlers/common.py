# /home/telegrambot/shift_tracker_bot/handlers/common.py

from datetime import date, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode


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
    """Показать пользователю его ID + информацию о чате/топике (если есть)"""
    user = update.effective_user
    msg = update.effective_message
    chat = update.effective_chat

    user_id = user.id
    username = user.username or "не установлен"
    first_name = user.first_name or ""
    last_name = user.last_name or ""

    # Данные о чате/топике
    chat_id = getattr(chat, "id", None)
    chat_title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or "личный диалог"
    is_forum = bool(getattr(chat, "is_forum", False))
    is_topic_message = bool(getattr(msg, "is_topic_message", False))
    topic_id = getattr(msg, "message_thread_id", None)

    # Название топика (если PTB/Telegram это отдает)
    topic_title = None
    try:
        topic_title = getattr(getattr(msg, "forum_topic", None), "name", None)
    except Exception:
        topic_title = None

    lines = [
        "👤 <b>Ваша информация:</b>",
        "",
        f"🆔 <b>Ваш ID:</b> <code>{user_id}</code>",
        f"📛 <b>Имя:</b> {first_name} {last_name}".strip(),
        f"🔗 <b>Username:</b> @{username}",
        "",
        "💬 <b>Текущий чат:</b>",
        f"• Название: {chat_title}",
        f"• Chat ID: <code>{chat_id}</code>",
        f"• Форумный чат (темы): {'да' if is_forum else 'нет'}",
    ]

    # Если сообщение пришло из темы — покажем её ID и (если есть) название
    if is_topic_message or (is_forum and topic_id is not None):
        lines.append(f"🧵 <b>ID топика:</b> <code>{topic_id}</code>")
        if topic_title:
            lines.append(f"🏷️ <b>Название топика:</b> {topic_title}")
        else:
            lines.append("🏷️ <b>Название топика:</b> (не удалось определить)")
    else:
        # Подсказка, как получить ID нужной темы
        lines.append("🧵 <i>Чтобы получить ID топика, вызовите /id прямо внутри нужной темы.</i>")

    message = "\n".join(lines)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
