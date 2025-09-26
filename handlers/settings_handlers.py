from telegram import Update
from telegram.ext import ContextTypes
from services.user_manager import user_manager
from services.auth_manager import auth_manager


async def set_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды смены графика /schedule"""
    user_id = update.effective_user.id

    # Инициализируем пользователя если его нет
    if user_id not in user_manager.users:
        user_manager.initialize_user(user_id)

    user = user_manager.users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Ошибка инициализации пользователя")
        return

    # Получаем текущий график (с значением по умолчанию)
    current_schedule = user.get("schedule", "стандартный")

    if not context.args:
        # Показываем доступные графики
        from database import schedule_repository
        schedules = schedule_repository.get_all_schedules()

        message = f"📋 <b>Доступные графики работы:</b>\n\n"
        message += f"📅 <b>Текущий график:</b> {current_schedule}\n\n"

        for schedule in schedules:
            message += f"• <b>{schedule['name']}</b>\n"
            message += f"  {schedule.get('description', 'Без описания')}\n"

        message += "\n🔄 <b>Использование:</b>\n"
        message += "/schedule [название] - сменить график\n"
        message += "Пример: /schedule короткий"

        await update.message.reply_text(message, parse_mode='HTML')
        return

    schedule_name = context.args[0].lower()

    if user_manager.set_user_schedule(user_id, schedule_name):
        await update.message.reply_text(f"✅ График изменен на: {schedule_name}")
    else:
        await update.message.reply_text(
            "❌ Неверное название графика. Используйте /schedule для просмотра доступных графиков")