from telegram import Update
from telegram.ext import ContextTypes
from services.user_manager import user_manager
from services.auth_manager import auth_manager
from utils.formatters import format_schedules_list


async def create_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /createschedule"""
    user_id = update.effective_user.id

    # Аутентифицируем пользователя
    if not auth_manager.authenticate_user(user_id, update.effective_user.username):
        await update.message.reply_text("❌ Сначала запустите /start для инициализации")
        return

    await update.message.reply_text(
        "📝 Создание пользовательского графика:\n\n"
        "Эта функция в активной разработке.\n"
        "Пока вы можете использовать стандартные графики:\n"
        "• стандартный (8:00-20:00 день, 20:00-8:00 ночь)\n"
        "• короткий (9:00-18:00 день, 19:00-7:00 ночь)\n\n"
        "Чтобы изменить график, используйте: /schedule [название]"
    )


async def my_schedules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /myschedules"""
    user_id = update.effective_user.id

    # Аутентифицируем пользователя
    if not auth_manager.is_user_approved(user_id):
        await update.message.reply_text("❌ Сначала запустите /start для инициализации")
        return

    user = user_manager.users.get(user_id)

    # Временные данные - потом из БД
    schedules = [
        {"name": "стандартный", "description": "8:00-20:00 день, 20:00-8:00 ночь"},
        {"name": "короткий", "description": "9:00-18:00 день, 19:00-7:00 ночь"}
    ]

    message = "📋 *Ваши графики работы:*\n\n"
    for schedule in schedules:
        message += f"• *{schedule['name']}* - {schedule['description']}\n"

    message += f"\n📊 *Текущий график:* {user['schedule'] if user else 'стандартный'}\n\n"
    message += "⚡ *Сменить график:*\n/schedule стандартный\n/schedule короткий"

    await update.message.reply_text(message, parse_mode='Markdown')