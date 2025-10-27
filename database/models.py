# /home/telegrambot/shift_tracker_bot/database/models.py

# Этот файл описывает модели данных и перечисления для системы планирования рабочих смен.
# Он служит для хранения и управления информацией о сменах, расписаниях, 
# пользовательских настройках, ролях и действиях администраторов.
# Такие модели обычно используются для работы с базой данных или в логике приложения.

from dataclasses import dataclass
from datetime import time, date, datetime
from enum import Enum
from typing import Optional, Dict, Any

# Типы смен
class ShiftType(Enum):
    DAY = "day"       # Дневная смена
    NIGHT = "night"   # Ночная смена
    REST = "rest"     # Отдых (выходной)

# Состояние пользователя в процессе взаимодействия с системой
class UserState(Enum):
    IDLE = "idle"                               # Без действия
    CREATING_SCHEDULE_NAME = "creating_schedule_name"   # Создание имени расписания
    CREATING_SCHEDULE_DAY = "creating_schedule_day"     # Добавление дневных смен
    CREATING_SCHEDULE_NIGHT = "creating_schedule_night" # Добавление ночных смен
    EDITING_SCHEDULE = "editing_schedule"               # Редактирование расписания

# Роль пользователя
#class UserRole(Enum):
    USER = "user"   # Обычный пользователь
    ADMIN = "admin" # Администратор

# Модель типа смены
@dataclass
class ShiftTypeModel:
    id: int
    name: str               # Системное название
    display_name: str       # Отображаемое название

# Рабочее расписание
@dataclass
class WorkSchedule:
    id: int
    name: str
    description: Optional[str]       # Описание расписания
    settings: Dict[str, Dict]        # Настройки (например, параметры смен)

# Пользовательское расписание
@dataclass
class UserCustomSchedule:
    id: int
    user_id: int
    name: str
    description: Optional[str]       # Описание
    is_active: bool                  # Активность расписания
    created_at: datetime             # Дата создания
    updated_at: datetime             # Дата обновления

# Настройки пользователя
@dataclass
class UserSettings:
    user_id: int
    schedule_id: Optional[int]       # ID системного расписания
    custom_schedule_id: Optional[int]# ID пользовательского расписания
    epoch_date: date                 # Начальная дата отсчета
    created_at: datetime
    updated_at: datetime

# Состояние пользователя с временными данными
@dataclass
class UserStateModel:
    user_id: int
    state: UserState                 # Текущее состояние пользователя
    temp_data: Dict[str, Any]        # Временные данные
    created_at: datetime
    updated_at: datetime

# Модель роли пользователя
@dataclass
class UserRoleModel:
    id: int
    name: str
    description: Optional[str]

# Сессия пользователя
@dataclass
class UserSession:
    id: int
    user_id: int
    token: str                       # Токен для аутентификации
    expires_at: datetime             # Время истечения сессии
    created_at: datetime

# Действия администратора
@dataclass
class AdminAction:
    id: int
    admin_id: int
    action_type: str                 # Тип действия
    target_user_id: Optional[int]    # ID пользователя, на которого направлено действие
    details: Dict                    # Дополнительные детали
    created_at: datetime
