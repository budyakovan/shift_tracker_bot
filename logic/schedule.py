from datetime import date, timedelta
import calendar
from config import START_DATE, INITIAL_SENIORS, INITIAL_JUNIORS, SCHEDULE, ROTATION_CONFIG


def calculate_days_since_start(target_date: date) -> int:
    start_date = date(*START_DATE)
    if target_date < start_date:
        return 0
    return (target_date - start_date).days


def get_rotated_groups_for_date(target_date: date) -> tuple:
    """
    Определяет составы групп на конкретную дату с учётом ротации.
    """
    days_passed = calculate_days_since_start(target_date)

    # Получаем настройки ротации из конфига
    senior_rot_days = ROTATION_CONFIG["senior_rotation_days"]
    junior_rot_days = ROTATION_CONFIG["junior_rotation_days"]
    pair_rot_days = ROTATION_CONFIG["pair_rotation_days"]

    # Определяем текущие позиции в ротациях
    senior_rot_pos = (days_passed // senior_rot_days) % 2
    junior_rot_pos = (days_passed // junior_rot_days) % 2
    pair_rot_pos = (days_passed // pair_rot_days) % 2

    # Выбираем старших и младших в зависимости от ротации
    if senior_rot_pos == 0:
        seniors = INITIAL_SENIORS
    else:
        seniors = [INITIAL_SENIORS[1], INITIAL_SENIORS[0]]

    if junior_rot_pos == 0:
        juniors = INITIAL_JUNIORS
    else:
        juniors = [INITIAL_JUNIORS[1], INITIAL_JUNIORS[0]]

    # Применяем ротацию связок (меняем местами группы)
    if pair_rot_pos == 0:
        group_1 = {"senior": seniors[0], "junior": juniors[0]}
        group_2 = {"senior": seniors[1], "junior": juniors[1]}
    else:
        group_1 = {"senior": seniors[1], "junior": juniors[1]}
        group_2 = {"senior": seniors[0], "junior": juniors[0]}

    return group_1, group_2


def get_schedule_period_for_date(target_date: date) -> str:
    """
    Определяет период графика для конкретной даты с учётом конфигурации периодов.
    """
    days_passed = calculate_days_since_start(target_date)
    pair_rot_days = ROTATION_CONFIG["pair_rotation_days"]
    periods_config = ROTATION_CONFIG["periods_config"]

    day_of_cycle = days_passed % pair_rot_days

    # Правильная логика определения периодов
    if day_of_cycle == periods_config["group1_works_days"][0]:
        return "first_day"
    elif day_of_cycle == periods_config["group2_works_days"][0]:
        return "second_day"
    elif day_of_cycle == periods_config["group1_works_days"][1]:
        return "first_night"
    elif day_of_cycle == periods_config["group2_works_days"][1]:
        return "second_night"
    else:
        return "day_off"

def generate_duty_message_for_date(target_date: date) -> str:
    group_1, group_2 = get_rotated_groups_for_date(target_date)
    period = get_schedule_period_for_date(target_date)

    weekdays_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    weekday_ru = weekdays_ru[target_date.weekday()]

    message = f"📅 График на {target_date.strftime('%d.%m.%Y')} ({weekday_ru})\n"

    if period == "first_day":
        message += "🔸 1-й рабочий день\n"
        message += f"   Группа 1 (Офис): {group_1['senior']} + {group_1['junior']}\n"
        message += f"   Время: {SCHEDULE['group_1_office']['day']}\n"
        message += f"   Группа 2 (Дом): {group_2['senior']} + {group_2['junior']}\n"
        message += f"   Время: {SCHEDULE['group_2_home']['day']}\n"

    elif period == "second_day":
        message += "🔸 2-й рабочий день\n"
        message += f"   Группа 1 (Офис): {group_1['senior']} + {group_1['junior']}\n"
        message += f"   Время: {SCHEDULE['group_1_office']['day']}\n"
        message += f"   Группа 2 (Дом): {group_2['senior']} + {group_2['junior']}\n"
        message += f"   Время: {SCHEDULE['group_2_home']['day']}\n"

    elif period == "first_night":
        message += "🌙 1-я рабочая ночь\n"
        message += f"   Группа 1 (Офис): {group_1['senior']} + {group_1['junior']}\n"
        message += f"   Время: {SCHEDULE['group_1_office']['night']}\n"
        message += f"   Группа 2 (Выходной): {group_2['senior']} + {group_2['junior']}\n"

    elif period == "second_night":
        message += "🌙 2-я рабочая ночь\n"
        message += f"   Группа 1 (Офис): {group_1['senior']} + {group_1['junior']}\n"
        message += f"   Время: {SCHEDULE['group_1_office']['night']}\n"
        message += f"   Группа 2 (Выходной): {group_2['senior']} + {group_2['junior']}\n"

    else:  # day_off
        message += "✅ Выходной день\n"

    return message


def generate_duty_message_for_period(days: int = 1) -> str:
    if days < 1 or days > 30:
        return "❌ Укажите количество дней от 1 до 30"

    today = date.today()
    messages = []
    for i in range(days):
        target_date = today + timedelta(days=i)
        messages.append(generate_duty_message_for_date(target_date))

    return "\n\n".join(messages)


def debug_rotation_for_period(days: int = 14):
    """Функция для отладки ротации на период"""
    today = date.today()
    results = []

    results.append("🔧 ОТЛАДКА РОТАЦИИ 🔧")
    results.append(f"START_DATE: {START_DATE}")
    results.append(f"Сегодня: {today.strftime('%d.%m.%Y')}")
    results.append("")

    for i in range(days):
        target_date = today + timedelta(days=i)
        days_passed = calculate_days_since_start(target_date)
        group_1, group_2 = get_rotated_groups_for_date(target_date)
        period = get_schedule_period_for_date(target_date)

        day_of_cycle = days_passed % ROTATION_CONFIG["pair_rotation_days"]

        # Определяем тип дня
        day_type = ""
        if period == "first_day":
            day_type = "1-й день"
        elif period == "second_day":
            day_type = "2-й день"
        elif period == "first_night":
            day_type = "1-я ночь"
        elif period == "second_night":
            day_type = "2-я ночь"
        else:
            day_type = "Выходной"

        results.append(
            f"{target_date.strftime('%d.%m.%Y')}: "
            f"День {days_passed} (цикл: {day_of_cycle}), "
            f"{day_type}, "
            f"Г1: {group_1['senior'][0]}.{group_1['junior'][0]}, "
            f"Г2: {group_2['senior'][0]}.{group_2['junior'][0]}"
        )

    return "\n".join(results)