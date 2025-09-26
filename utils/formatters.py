from datetime import date
from typing import Dict


def format_shift_message(shift_info: Dict) -> str:
    """Форматирует информацию о смене в читаемое сообщение"""
    date_str = shift_info["date"].strftime("%d.%m.%Y (%A)")

    message = f"📅 {date_str}\n"
    message += f"🎯 {shift_info['description']}\n"
    message += f"🔢 День цикла: {shift_info['day_number']}/7\n"

    if shift_info["is_working"]:
        message += f"⏰ Время: {shift_info['start_time']} - {shift_info['end_time']}\n"

        # Для ночной смены добавляем предупреждение
        if shift_info["type"] == "night":
            next_day = shift_info["date"] + timedelta(days=1)
            message += f"⚠️ Завершается {next_day.strftime('%d.%m')} в {shift_info['end_time']}\n"
    else:
        message += "🎉 Отдыхайте! Отличного выходного!\n"

    return message


def format_schedules_list(schedules: list) -> str:
    """Форматирует список графиков"""
    if not schedules:
        return "📋 У вас пока нет графиков. Создайте первый с помощью /createschedule"

    message = "📋 Ваши графики:\n\n"
    for i, schedule in enumerate(schedules, 1):
        message += f"{i}. {schedule['name']}"
        if 'description' in schedule:
            message += f" - {schedule['description']}"
        message += "\n"

    return message


def format_users_list(users: list) -> str:
    """Форматирует список пользователей"""
    if not users:
        return "📋 Пользователей не найдено"

    message = "👥 Список пользователей:\n\n"
    for user in users:
        message += f"🆔 ID: {user['user_id']}\n"
        message += f"🎯 Роль: {user['role']}\n"
        message += f"📅 Нулевой день: {user['epoch_date']}\n"
        message += f"📊 Графиков: {user['custom_schedules']}\n"
        message += "─" * 20 + "\n"

    return message