from datetime import date, timedelta
from typing import Dict


class ShiftCalculator:
    def __init__(self, epoch_date: date):
        self.epoch_date = epoch_date

    def calculate_shift(self, target_date: date) -> Dict[str, any]:
        """Вычисляет смену для заданной даты"""
        delta = (target_date - self.epoch_date).days
        day_number = delta % 8

        print(
            f"DEBUG: epoch: {self.epoch_date}, target: {target_date}, delta: {delta}, day_number: {day_number}")  # Отладочная информация

        if day_number in (0, 1):
            return {
                "type": "day",
                "day_number": day_number,
                "display_type": "День",
                "is_working": True
            }
        elif day_number in (2, 3):
            return {
                "type": "night",
                "day_number": day_number,
                "display_type": "Ночь",
                "is_working": True
            }
        else:
            return {
                "type": "rest",
                "day_number": day_number,
                "display_type": "Выходной",
                "is_working": False
            }

    def get_shift_info(self, target_date: date, schedule_name: str = "стандартный") -> Dict[str, any]:
        """Получает полную информацию о смене"""
        shift_info = self.calculate_shift(target_date)

        # Добавляем информацию о времени в зависимости от графика
        time_info = self._get_time_info(shift_info["type"], schedule_name)

        return {**shift_info, **time_info, "date": target_date}

    def _get_time_info(self, shift_type: str, schedule_name: str) -> Dict[str, any]:
        """Возвращает информацию о времени для типа смены"""
        if schedule_name == "стандартный":
            if shift_type == "day":
                return {
                    "start_time": "08:00",
                    "end_time": "20:00",
                    "description": "Дневная смена 8:00-20:00"
                }
            elif shift_type == "night":
                return {
                    "start_time": "20:00",
                    "end_time": "08:00",
                    "description": "Ночная смена 20:00-8:00"
                }
        elif schedule_name == "короткий":
            if shift_type == "day":
                return {
                    "start_time": "09:00",
                    "end_time": "18:00",
                    "description": "Дневная смена 9:00-18:00"
                }
            elif shift_type == "night":
                return {
                    "start_time": "19:00",
                    "end_time": "07:00",
                    "description": "Ночная смена 19:00-7:00"
                }

        return {
            "start_time": None,
            "end_time": None,
            "description": "Выходной день"
        }