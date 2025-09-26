from dataclasses import dataclass
from datetime import time, date, datetime
from enum import Enum
from typing import Optional, Dict, Any

class ShiftType(Enum):
    DAY = "day"
    NIGHT = "night"
    REST = "rest"

class UserState(Enum):
    IDLE = "idle"
    CREATING_SCHEDULE_NAME = "creating_schedule_name"
    CREATING_SCHEDULE_DAY = "creating_schedule_day"
    CREATING_SCHEDULE_NIGHT = "creating_schedule_night"
    EDITING_SCHEDULE = "editing_schedule"

class UserRole(Enum):
    USER = "user"
    ADMIN = "admin"

@dataclass
class ShiftTypeModel:
    id: int
    name: str
    display_name: str

@dataclass
class WorkSchedule:
    id: int
    name: str
    description: Optional[str]
    settings: Dict[str, Dict]

@dataclass
class UserCustomSchedule:
    id: int
    user_id: int
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

@dataclass
class UserSettings:
    user_id: int
    schedule_id: Optional[int]
    custom_schedule_id: Optional[int]
    epoch_date: date
    created_at: datetime
    updated_at: datetime

@dataclass
class UserStateModel:
    user_id: int
    state: UserState
    temp_data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

@dataclass
class UserRoleModel:
    id: int
    name: str
    description: Optional[str]

@dataclass
class UserSession:
    id: int
    user_id: int
    token: str
    expires_at: datetime
    created_at: datetime

@dataclass
class AdminAction:
    id: int
    admin_id: int
    action_type: str
    target_user_id: Optional[int]
    details: Dict
    created_at: datetime