from .repository import UserRepository, ScheduleRepository, ShiftRepository

# Создаем глобальные экземпляры репозиториев
user_repository = UserRepository()
schedule_repository = ScheduleRepository()
shift_repository = ShiftRepository()

__all__ = ['user_repository', 'schedule_repository', 'shift_repository']
