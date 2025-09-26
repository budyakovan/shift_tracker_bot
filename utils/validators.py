from datetime import datetime
from typing import Optional, Tuple


def parse_date_input(text: str) -> Optional[Tuple[int, int, int]]:
    """
    Парсит ввод даты в форматах:
    - DD.MM (текущий год)
    - DD.MM.YYYY
    - DD-MM-YYYY
    - DD/MM/YYYY
    """
    try:
        # Убираем лишние пробелы
        text = text.strip()

        # Заменяем разделители на точки
        text = text.replace('-', '.').replace('/', '.')

        # Разбиваем на части
        parts = text.split('.')

        if len(parts) == 2:
            # Формат DD.MM - используем текущий год
            day, month = int(parts[0]), int(parts[1])
            year = datetime.now().year
            return day, month, year

        elif len(parts) == 3:
            # Формат DD.MM.YYYY
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            # Корректируем год если введен короткий формат
            if year < 100:
                year += 2000
            return day, month, year

        return None

    except (ValueError, IndexError):
        return None


def is_valid_date(day: int, month: int, year: int) -> bool:
    """Проверяет, является ли дата valid"""
    try:
        datetime(year, month, day)
        return True
    except ValueError:
        return False