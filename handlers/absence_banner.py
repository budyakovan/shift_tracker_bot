# /home/telegrambot/shift_tracker_bot/handlers/absence_banner.py
# -*- coding: utf-8 -*-

import re
from datetime import datetime
from typing import Tuple, List, Dict, Any
from telegram.constants import ParseMode
from database.absence_repository import get_absence_on_date

# Ищем дату в формате YYYY-MM-DD (группы: год, месяц, день)
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _get_user_display_name(user_id: int) -> str:
    """
    Получает ФИО и username пользователя по user_id из базы данных.
    """
    try:
        # Пробуем получить информацию о пользователе из групп
        from database import time_repository as time_repo

        # Ищем пользователя во всех группах
        groups = time_repo.list_groups() or []
        for group in groups:
            info = time_repo.get_group_info(group.get("key"))
            if not info:
                continue

            members = info.get("members") or []
            for member in members:
                if str(member.get("user_id")) == str(user_id):
                    first_name = (member.get("first_name") or "").strip()
                    last_name = (member.get("last_name") or "").strip()
                    username = (member.get("username") or "").strip()

                    name_parts = []
                    if first_name or last_name:
                        name_parts.append(f"{first_name} {last_name}".strip())
                    if username:
                        name_parts.append(f"@{username}")

                    return " • ".join(name_parts) if name_parts else f"ID: {user_id}"

        # Если пользователь не найден в группах, возвращаем ID
        return f"ID: {user_id}"

    except Exception as e:
        print(f"Error getting user info for {user_id}: {e}")
        return f"ID: {user_id}"


def inject_absence_banner_for_text(raw_text: str, user_id: int) -> Tuple[str, bool]:
    """
    Возвращает (текст_с_возможным_баннером, использован_html_баннер).
    Баннер добавляется только если день попадает в отпуск/больничный.
    """
    if not raw_text:
        return raw_text, False

    # Пытаемся найти первую дату в тексте
    m = DATE_RE.search(raw_text)
    if not m:
        return raw_text, False

    # Преобразуем найденную дату к date; при ошибке — без баннера
    try:
        target_date = datetime.strptime(m.group(0), "%Y-%m-%d").date()
    except Exception:
        return raw_text, False

    # Проверяем наличие отсутствия в выбранную дату
    absence = get_absence_on_date(user_id, target_date)
    if not absence:
        return raw_text, False

    # Получаем информацию о пользователе
    user_display = _get_user_display_name(user_id)

    # Подбираем эмодзи и заголовок по типу отсутствия
    emoji = "🏖" if absence["absence_type"] == "vacation" else "🤒"
    label = "Отпуск" if absence["absence_type"] == "vacation" else "Больничный"

    # Формируем HTML-баннер с информацией о пользователе
    banner = (
            f"<b>{emoji} {label}</b>: {user_display} • {absence['date_from']}—{absence['date_to']}"
            + (f" — {absence['comment']}" if absence.get("comment") else "")
            + "\n⚠️ <b>День попадает в отсутствие</b>\n"
    )
    # Баннер вставляется в начало исходного текста
    return banner + raw_text, True


async def reply_with_absence_banner(update, text: str, user_id: int):
    """
    Всегда отправляем parse_mode=HTML, потому что исходные тексты уже содержат <b>, <code> и т.п.
    Если отсутствия нет — просто отправим исходный текст как HTML.
    """
    new_text, _ = inject_absence_banner_for_text(text, user_id)
    await update.message.reply_text(new_text, parse_mode=ParseMode.HTML)


def check_absences_for_shift_users(shift_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Проверяет отсутствия для всех пользователей в данных смены и добавляет предупреждения.

    Args:
        shift_data: Данные смены в формате:
            {
                'date': '2024-09-30',
                'groups': [
                    {
                        'name': 'Токарев',
                        'users': [
                            {'user_id': 123, 'first_name': 'Владислав', ...},
                            ...
                        ]
                    },
                    ...
                ]
            }

    Returns:
        Модифицированные данные с добавлением поля 'absence_warnings'
    """
    if not shift_data or 'date' not in shift_data:
        return shift_data

    try:
        shift_date = datetime.strptime(shift_data['date'], "%Y-%m-%d").date()
    except Exception:
        return shift_data

    absence_warnings = []

    # Проверяем всех пользователей во всех группах
    for group in shift_data.get('groups', []):
        for user in group.get('users', []):
            user_id = user.get('user_id')
            if not user_id:
                continue

            # Проверяем отсутствие на дату смены
            absence = get_absence_on_date(user_id, shift_date)
            if absence:
                emoji = "🏖" if absence["absence_type"] == "vacation" else "🤒"
                label = "отпуске" if absence["absence_type"] == "vacation" else "больничном"

                user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                if not user_name:
                    user_name = f"user_id={user_id}"

                warning = {
                    'user_id': user_id,
                    'user_name': user_name,
                    'username': user.get('username', ''),
                    'absence_type': absence["absence_type"],
                    'date_from': absence['date_from'],
                    'date_to': absence['date_to'],
                    'emoji': emoji,
                    'label': label,
                    'comment': absence.get('comment', '')
                }
                absence_warnings.append(warning)

    shift_data['absence_warnings'] = absence_warnings
    return shift_data


def format_shift_with_absence_warnings(shift_data: Dict[str, Any]) -> str:
    """
    Форматирует данные смены с предупреждениями об отсутствиях.

    Returns:
        Отформатированная строка с информацией о смене и предупреждениями
    """
    if not shift_data:
        return "Нет данных о смене"

    # Базовое форматирование смены (ваш существующий код)
    lines = []

    # Дата и день недели
    date_str = shift_data.get('date', '')
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = date_obj.strftime("%A")
        lines.append(f"🗓 {weekday}, {date_str}")
    except Exception:
        lines.append(f"🗓 {date_str}")

    # Группы и пользователи
    for group in shift_data.get('groups', []):
        lines.append(f"\nГруппа {group.get('name', '')}")

        # Время смены
        if group.get('time'):
            lines.append(f"🕒 {group.get('time')}")

        # Пользователи в группе
        for user in group.get('users', []):
            user_line = _fmt_user_line(user)
            lines.append(user_line)

    # Добавляем предупреждения об отсутствиях
    warnings = shift_data.get('absence_warnings', [])
    if warnings:
        lines.append("\n⚠️ <b>Предупреждения об отсутствиях:</b>")
        for warning in warnings:
            user_display = warning['user_name']
            if warning['username']:
                user_display += f" @{warning['username']}"

            comment_text = f" — {warning['comment']}" if warning.get('comment') else ""
            lines.append(
                f"• {warning['emoji']} {user_display} в {warning['label']}: "
                f"{warning['date_from']}—{warning['date_to']}{comment_text}"
            )

    return "\n".join(lines)


# Вспомогательная функция для форматирования пользователя
def _fmt_user_line(user_data: Dict[str, Any]) -> str:
    """
    Форматирует строку пользователя в формате: '👤 Имя Фамилия 🔗 @username'
    """
    first_name = user_data.get('first_name', '').strip()
    last_name = user_data.get('last_name', '').strip()
    username = user_data.get('username', user_data.get('tg_username', '')).strip()
    user_id = user_data.get('user_id')

    name_parts = []
    if first_name or last_name:
        name_parts.append(f"{first_name} {last_name}".strip())
    else:
        name_parts.append(f"user_id={user_id}")

    if username:
        name_parts.append(f"🔗 @{username}")

    return "👤 " + " ".join(name_parts)


async def send_shift_with_absence_check(update, shift_data: Dict[str, Any]):
    """
    Основная функция: проверяет отсутствия и отправляет смену с предупреждениями.
    """
    # Проверяем отсутствия
    shift_data_with_warnings = check_absences_for_shift_users(shift_data)

    # Форматируем результат
    formatted_text = format_shift_with_absence_warnings(shift_data_with_warnings)

    # Отправляем с parse_mode=HTML для поддержки жирного текста в предупреждениях
    await update.message.reply_text(formatted_text, parse_mode=ParseMode.HTML)