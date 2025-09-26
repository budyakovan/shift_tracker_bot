from datetime import date
from typing import Dict, Optional
from services.shift_calculator import ShiftCalculator
from database import user_repository  # ← Добавьте импорт
import logging

logger = logging.getLogger(__name__)

class UserManager:
    def __init__(self):
        # Временное хранилище пользователей (только для настроек, не для ролей!)
        self.users = {}
        self.user_repo = user_repository  # ← Добавьте репозиторий

    def initialize_user(self, user_id: int, username: str = None) -> bool:
        """Инициализирует пользователя с настройками по умолчанию"""
        try:
            if user_id not in self.users:
                self.users[user_id] = {
                    "username": username,
                    "schedule": "стандартный",  # ← ДОБАВЬТЕ ЭТОТ КЛЮЧ
                    "epoch_date": date(2025, 8, 28),
                    "calculator": ShiftCalculator(date(2025, 8, 28))
                }
            return True
        except Exception as e:
            logger.error(f"Error initializing user {user_id}: {e}")
            return False

    def get_user_shift(self, user_id: int, target_date: date) -> Optional[Dict]:
        """Получает информацию о смене пользователя"""
        user = self.users.get(user_id)

        # Если пользователь не инициализирован - инициализируем
        if not user:
            self.initialize_user(user_id)
            user = self.users.get(user_id)
            if not user:
                return None

        try:
            return user["calculator"].get_shift_info(target_date, user["schedule"])
        except Exception as e:
            print(f"Error getting shift: {e}")
            return None

    def set_user_schedule(self, user_id: int, schedule_name: str) -> bool:
        """Устанавливает график для пользователя"""
        if user_id not in self.users:
            self.initialize_user(user_id)

        # Проверяем существование графика в базе
        from database import schedule_repository
        available_schedules = schedule_repository.get_all_schedules()
        schedule_names = [s['name'] for s in available_schedules]

        if schedule_name not in schedule_names:
            return False

        self.users[user_id]["schedule"] = schedule_name
        return True

    def get_user(self, user_id: int):
        """Получает информацию о пользователе ИЗ БАЗЫ ДАННЫХ"""
        try:
            # Важно: получаем данные из базы, а не из кэша!
            return self.user_repo.get_user(user_id)
        except Exception as e:
            logger.error(f"Error getting user from DB: {e}")
            return None

    def is_user_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        user_data = self.get_user(user_id)  # ← Из базы данных!
        return user_data and user_data.get('role') == 'admin'


# Глобальный экземпляр менеджера пользователей
user_manager = UserManager()