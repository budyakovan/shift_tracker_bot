from telegram import Update
from telegram.ext import ContextTypes
from keyboards.main_menu import get_main_keyboard
from services.auth_manager import auth_manager
from services.user_manager import user_manager


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user

    # Регистрируем пользователя с именем и фамилией
    auth_manager.register_user(
        user.id,
        user.username,
        user.first_name,
        user.last_name
    )

    # Проверяем, approved ли пользователь
    if auth_manager.is_user_approved(user.id):
        # Инициализируем пользователя в user_manager
        user_manager.initialize_user(user.id, user.username)

        welcome_text = (
            "👋 <b>Добро пожаловать в Shift Tracker Bot!</b>\n\n"
            "📅 Я помогу вам отслеживать ваш сменный график работы.\n\n"
            "⚡ <b>Что я умею:</b>\n"
            "• Показывать ваши смены на сегодня и завтра\n"
            "• Работать с разными графиками работы\n"
            "• Показывать смены на любую дату\n"
            "• Управлять вашими настройками\n\n"
        )

        # Добавляем информацию о правах для админов
        if auth_manager.is_admin(user.id):
            welcome_text += "⚡ <b>Вы являетесь администратором системы!</b>\n"
            welcome_text += "Используйте /admin_help для просмотра админ. команд\n\n"

        welcome_text += (
            "📋 <b>Быстрый старт:</b>\n"
            "• Нажмите '📅 Сегодня' для просмотра сегодняшней смены\n"
            "• Используйте /help для полной справки\n"
            "• Пишите даты в формате ДД.ММ для просмотра смен\n\n"
            "🚀 <b>Приятного использования!</b>"
        )

        await update.message.reply_text(welcome_text, parse_mode='HTML', reply_markup=get_main_keyboard())
    else:
        # Пользователь не approved
        await update.message.reply_text(
            f"❌ <b>Ваш аккаунт ожидает одобрения</b>\n\n"
            f"🆔 <b>Ваш ID:</b> <code>{user.id}</code>\n"
            f"📋 Передайте этот ID администратору для активации.\n\n"
            f"После одобрения вы сможете:\n"
            f"• Просматривать свои смены\n"
            f"• Использовать все функции бота\n"
            f"• Настраивать графики работы\n\n"
            f"⏳ Обычно одобрение занимает несколько минут.",
            parse_mode='HTML'
        )