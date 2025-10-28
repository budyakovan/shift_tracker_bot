# /home/telegrambot/shift_tracker_bot/database/time_repository.py
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Назначение файла
# -----------------------------------------------------------------------------
# Этот модуль реализует операции над сущностями «тайм-профили» и «тайм-группы»
# для бота расписаний. Здесь:
#   • читаются/создаются/обновляются time_profiles, time_profile_slots, time_groups;
#   • управляются участники time_group_members;
#   • выдаётся сводная информация по группе/профилю для админских команд.
#
# Общие принципы:
#   • Соединение с БД берётся из db_connection (psycopg2), курсоры — контекстные.
#   • Все SQL — параметризованные (без конкатенации пользовательского ввода).
#   • Форматы возврата — словари и списки словарей (для удобства сериализации).
# -----------------------------------------------------------------------------

import logging
from datetime import datetime, date as _date_cls, date
from .connection import db_connection
from datetime import datetime, date as _date_cls, date, time as dtime, timedelta  # ← ДОБАВИЛИ dtime, timedelta

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo  # py>=3.9
except Exception:
    ZoneInfo = None

# Единый Moscow TZ для всех расчётов сегментов
if ZoneInfo:
    MSK = ZoneInfo("Europe/Moscow")
else:
    MSK = None


def now_local() -> datetime:
    """
    Текущее «операционное» локальное время бота.
    В проекте UI и логика ориентируются на Москву, поэтому IANA tz — Europe/Moscow.
    """
    if ZoneInfo:
        return datetime.now(ZoneInfo("Europe/Moscow"))
    # Фолбэк без tzinfo (лучше установить python3-tzdata, чтобы работал ZoneInfo)
    return datetime.now()

def today_local():
    """Текущая локальная дата (короткая обёртка)."""
    return now_local().date()

# -----------------------------------------------------------------------------#
# Вспомогательные хелперы
# -----------------------------------------------------------------------------#

def _as_date(x):
    """Приводит значение к date, если возможно (поддерживает ISO-строку)."""
    if isinstance(x, _date_cls):
        return x
    try:
        return _date_cls.fromisoformat(str(x))
    except Exception:
        return None


def _resolve_group_id(cur, group_key: str) -> int | None:
    """Возвращает id группы по ключу, либо None."""
    cur.execute("SELECT id FROM time_groups WHERE key = %s", (group_key,))
    r = cur.fetchone()
    return r[0] if r else None


# -----------------------------------------------------------------------------#
# Чтение подробной информации по тайм-группе
# -----------------------------------------------------------------------------#

def get_group_info(group_key: str):
    """
    Вернуть подробную информацию по тайм-группе:
    - key, name, profile_key
    - epoch, period, rotation_dir
    - tz (жёстко Europe/Moscow для консистентности UI)
    - members: [{user_id, base_pos, username, first_name, last_name}, ...]
    - slots:   [{pos, name, start, end, start_time, end_time}, ...]
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        # 1) Шапка
        cur.execute(
            """
            SELECT tg.id,
                   tg.key,
                   tg.name,
                   tp.key AS profile_key,
                   tg.epoch,
                   tg.rotation_period_days,
                   tg.rotation_dir,
                   tg.tz_name,
                   tg.tz_offset_hours
            FROM time_groups tg
            JOIN time_profiles tp ON tp.id = tg.profile_id
            WHERE tg.key = %s
            """,
            (group_key,),
        )
        row = cur.fetchone()
        if not row:
            logger.debug("time_repo.get_group_info: key=%s -> NOT FOUND", group_key)
            return None

        group_id = row[0]
        info = {
            "key": row[1],
            "name": row[2],
            "profile_key": row[3],
            "epoch": row[4],
            "period": row[5],
            "rotation_dir": row[6],
            # TZ из БД игнорируем — фикс на Москву (как и раньше)
            "tz": "Europe/Moscow",
            "tz_name": "Europe/Moscow",
            "tz_offset_hours": 0,
            "members": [],
            "slots": [],
        }

        # 2) Участники
        cur.execute(
            """
            SELECT m.user_id,
                   m.base_pos,
                   u.username,
                   u.first_name,
                   u.last_name
            FROM time_group_members m
            LEFT JOIN users u ON u.user_id = m.user_id
            WHERE m.time_group_id = %s
            ORDER BY m.base_pos,
                     COALESCE(u.first_name,''), COALESCE(u.last_name,''),
                     COALESCE(u.username,''), m.user_id::text
            """,
            (group_id,),
        )
        members = cur.fetchall() or []
        info["members"] = [
            {
                "user_id": r[0],
                "base_pos": r[1],
                "username": r[2],
                "first_name": r[3],
                "last_name": r[4],
            }
            for r in members
        ]

        # 3) Слоты профиля
        cur.execute(
            """
            SELECT s.pos, s.name, s.start_time, s.end_time
            FROM time_profile_slots s
            JOIN time_profiles tp ON tp.id = s.profile_id
            WHERE tp.key = %s
            ORDER BY s.pos
            """,
            (info["profile_key"],),
        )
        slots = cur.fetchall() or []

        def _fmt(t):
            try:
                return t.strftime("%H:%M")
            except Exception:
                return str(t)[:5]

        info["slots"] = [
            {
                "pos": r[0],
                "name": r[1] or "",
                "start": _fmt(r[2]),
                "end": _fmt(r[3]),
                "start_time": r[2],
                "end_time": r[3],
            }
            for r in slots
        ]

    logger.debug(
        "time_repo.get_group_info: key=%s members=%d slots=%d tz=%s",
        info["key"], len(info["members"]), len(info["slots"]),
        info.get("tz_name") or info.get("tz")
    )
    return info


# -----------------------------------------------------------------------------#
# Профили времени
# -----------------------------------------------------------------------------#

def create_profile(key: str, name: str, tz_name: str | None = None, tz_offset_hours: int = 0):
    """Создать/обновить профиль времени (UPSERT по key)."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO time_profiles (key, name, tz_name, tz_offset_hours)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE
                SET name = EXCLUDED.name,
                    tz_name = EXCLUDED.tz_name,
                    tz_offset_hours = EXCLUDED.tz_offset_hours
            RETURNING id
            """,
            (key, name, tz_name, tz_offset_hours),
        )
        return cur.fetchone()[0]


def list_profiles():
    """Вернуть список всех профилей времени (как есть в БД)."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT key, name, tz_name, tz_offset_hours
            FROM time_profiles
            ORDER BY name
            """
        )
        rows = cur.fetchall() or []
        return [
            {"key": r[0], "name": r[1], "tz_name": r[2], "tz_offset_hours": r[3]}
            for r in rows
        ]


def add_slot(profile_key: str, pos: int, start: str, end: str, name: str | None = None):
    """Добавить/обновить слот профиля (UPSERT по (profile_id, pos))."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO time_profile_slots (profile_id, pos, name, start_time, end_time)
            SELECT tp.id, %s, %s, %s, %s
            FROM time_profiles tp
            WHERE tp.key = %s
            ON CONFLICT (profile_id, pos) DO UPDATE
                SET name = EXCLUDED.name,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time
            RETURNING id
            """,
            (pos, name, start, end, profile_key),
        )
        return cur.fetchone()[0]


def clear_profile_slots(profile_key: str) -> int:
    """Очистить все слоты профиля. Возвращает кол-во удалённых строк."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM time_profile_slots
            WHERE profile_id = (SELECT id FROM time_profiles WHERE key = %s)
            """,
            (profile_key,),
        )
        return cur.rowcount


def get_profile_info(profile_key: str):
    """
    Вернуть профиль времени и его слоты.

    {
      "key": str,
      "name": str|None,
      "tz_name": str|None,
      "slots": [{"pos": int, "start": "HH:MM", "end": "HH:MM", "name": str|None}, ...]
    }
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, key, name, tz_name
            FROM time_profiles
            WHERE key = %s
            """,
            (profile_key,),
        )
        row = cur.fetchone()
        if not row:
            return None

        profile_id, key, name, tz_name = row
        profile = {"key": key, "name": name, "tz_name": tz_name, "slots": []}

        cur.execute(
            """
            SELECT pos, start_time, end_time, name
            FROM time_profile_slots
            WHERE profile_id = %s
            ORDER BY pos
            """,
            (profile_id,),
        )
        for pos, start_time, end_time, sname in cur.fetchall():
            profile["slots"].append(
                {
                    "pos": pos,
                    "start": start_time.strftime("%H:%M"),
                    "end": end_time.strftime("%H:%M"),
                    "name": sname,
                }
            )

        return profile


# -----------------------------------------------------------------------------#
# Группы времени
# -----------------------------------------------------------------------------#

def create_time_group(
    group_key: str,
    profile_key: str,
    epoch,                     # str | date | datetime
    period_days: int,
    rotation_dir: int = 1,
    tz_name: str | None = None,   # игнорируем — tz берём из профиля
    name: str | None = None,      # «человеческое» имя группы
):
    """Создать/обновить тайм-группу. Часовой пояс ВСЕГДА наследуем от профиля."""
    # Нормализация epoch
    if isinstance(epoch, _date_cls):
        epoch_date = epoch if not isinstance(epoch, datetime) else epoch.date()
    elif isinstance(epoch, str):
        s = epoch.strip()
        for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                epoch_date = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
        else:
            # формат ДД.ММ -> текущий год
            try:
                d, m = s.split(".")
                epoch_date = _date_cls(_date_cls.today().year, int(m), int(d))
            except Exception as e:
                raise ValueError(f"Неверный формат даты epoch: {epoch!r}") from e
    else:
        raise TypeError(f"epoch должен быть str или date, получено: {type(epoch).__name__}")

    with db_connection.connect() as conn, conn.cursor() as cur:
        # 1) получаем профиль (берём tz поля отсюда)
        cur.execute(
            "SELECT id, name, tz_name, tz_offset_hours FROM time_profiles WHERE key = %s",
            (profile_key,),
        )
        prof = cur.fetchone()
        if not prof:
            raise ValueError(
                f"Профиль времени '{profile_key}' не найден. Сначала создайте его (/admin_time_profile_create)."
            )

        profile_id, profile_name, prof_tz_name, prof_tz_offset = prof
        group_name = (name or profile_name or group_key).strip()

        # 2) UPSERT группы; tz всегда берём из профиля
        cur.execute(
            """
            INSERT INTO time_groups
                (key,  name,       profile_id, epoch, rotation_period_days, rotation_dir, tz_name, tz_offset_hours)
            VALUES
                (%s,   %s,         %s,         %s,    %s,                   %s,          %s,      %s)
            ON CONFLICT (key) DO UPDATE SET
                name                 = EXCLUDED.name,
                profile_id           = EXCLUDED.profile_id,
                epoch                = EXCLUDED.epoch,
                rotation_period_days = EXCLUDED.rotation_period_days,
                rotation_dir         = EXCLUDED.rotation_dir,
                tz_name              = EXCLUDED.tz_name,
                tz_offset_hours      = EXCLUDED.tz_offset_hours
            RETURNING id
            """,
            (
                group_key,
                group_name,
                profile_id,
                epoch_date,
                period_days,
                rotation_dir,
                prof_tz_name,
                prof_tz_offset,
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Не удалось создать/обновить тайм-группу (RETURNING не вернул id)")
        return row[0]


def delete_time_group(group_key: str) -> bool:
    """Удалить тайм-группу по ключу. Возвращает True, если что-то удалилось."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM time_groups WHERE key = %s", (group_key,))
        return cur.rowcount > 0

# ---- Совместимые алиасы под разные вызовы из хендлеров ----
def set_epoch(group_key: str, epoch: _date_cls) -> bool:
    """Алиас к set_group_epoch (совместимость)."""
    return set_group_epoch(group_key, epoch)

def update_group_epoch(group_key: str, epoch: _date_cls) -> bool:
    """Алиас к set_group_epoch (совместимость)."""
    return set_group_epoch(group_key, epoch)

def admin_time_groups_set_epoch(group_key: str, epoch: _date_cls) -> bool:
    """Алиас к set_group_epoch (совместимость)."""
    return set_group_epoch(group_key, epoch)


def set_group_tz(group_key: str, tz_name: str) -> bool:
    """Установить IANA-часовой пояс для тайм-группы."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE time_groups
               SET tz_name = %s
             WHERE key = %s
            """,
            (tz_name, group_key),
        )
        return cur.rowcount > 0


def set_group_period(group_key: str, days: int) -> bool:
    """Установить период ротации (в днях). 0 = без ротации."""
    if days < 0:
        raise ValueError("period (days) не может быть отрицательным")
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE time_groups
               SET rotation_period_days = %s
             WHERE key = %s
            """,
            (days, group_key),
        )
        return cur.rowcount > 0


def set_group_epoch(group_key: str, epoch: _date_cls) -> bool:
    """Обновить epoch у тайм-группы."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        # В некоторых схемах нет колонки updated_at — обновляем только epoch.
        cur.execute(
            """
            UPDATE time_groups
               SET epoch = %s
             WHERE key = %s
            """,
            (epoch, group_key),
        )
        return cur.rowcount > 0


def update_name(key: str, new_name: str) -> bool:
    """Переименование группы по ключу."""
    if not key or not new_name:
        return False
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE time_groups SET name = %s WHERE key = %s",
            (new_name.strip(), key.strip().lower()),
        )
        return cur.rowcount > 0


# -----------------------------------------------------------------------------#
# Список тайм-групп
# -----------------------------------------------------------------------------#
def list_groups() -> list[dict]:
    """
    Вернуть список всех тайм-групп.
    Формат элементов:
      {
        "key": str,
        "name": str|None,
        "profile_key": str|None,
        "epoch": date|str|None,
        "rotation_period_days": int|None,
        "rotation_dir": int|None,
        "tz_name": str|None,
        "tz_offset_hours": int|None,
      }
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                tg.key,
                tg.name,
                tp.key    AS profile_key,
                tg.epoch,
                tg.rotation_period_days,
                tg.rotation_dir,
                tg.tz_name,
                tg.tz_offset_hours
            FROM time_groups tg
            LEFT JOIN time_profiles tp ON tp.id = tg.profile_id
            ORDER BY COALESCE(tg.name, tg.key)
            """
        )
        rows = cur.fetchall() or []
        return [
            {
                "key": r[0], "name": r[1], "profile_key": r[2], "epoch": r[3],
                "rotation_period_days": r[4], "rotation_dir": r[5],
                "tz_name": r[6], "tz_offset_hours": r[7],
            } for r in rows
        ]

# Алиасы под разные старые вызовы
def groups_list() -> list[dict]:
    return list_groups()

def list_time_groups() -> list[dict]:
    return list_groups()

# -----------------------------------------------------------------------------#
# Участники групп
# -----------------------------------------------------------------------------#

def add_user_to_group(group_key: str, user_id: int, base_pos: int) -> bool:
    """Добавить пользователя в тайм-группу/обновить его базовую позицию."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        group_id = _resolve_group_id(cur, group_key)
        if group_id is None:
            return False
        cur.execute(
            """
            INSERT INTO time_group_members (time_group_id, user_id, base_pos)
            VALUES (%s, %s, %s)
            ON CONFLICT (time_group_id, user_id) DO UPDATE
                SET base_pos = EXCLUDED.base_pos
            """,
            (group_id, user_id, base_pos),
        )
        return True


def remove_user_from_group(group_key: str, user_id: int) -> bool:
    """Удалить пользователя из тайм-группы."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        group_id = _resolve_group_id(cur, group_key)
        if group_id is None:
            return False
        cur.execute(
            """
            DELETE FROM time_group_members
             WHERE time_group_id = %s AND user_id = %s
            """,
            (group_id, user_id),
        )
        return cur.rowcount > 0


def set_user_pos(group_key: str, user_id: int, pos: int) -> bool:
    """
    Обновляет базовую позицию участника в группе (time_group_members.base_pos).
    Если записи нет — создаёт.
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        group_id = _resolve_group_id(cur, group_key)
        if group_id is None:
            return False

        # UPDATE → если 0 строк, делаем INSERT (с ON CONFLICT)
        cur.execute(
            """
            UPDATE time_group_members
               SET base_pos = %s
             WHERE time_group_id = %s AND user_id = %s
            """,
            (int(pos), group_id, int(user_id)),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO time_group_members (time_group_id, user_id, base_pos)
                VALUES (%s, %s, %s)
                ON CONFLICT (time_group_id, user_id) DO UPDATE
                    SET base_pos = EXCLUDED.base_pos
                """,
                (group_id, int(user_id), int(pos)),
            )
        return True


def list_group_users(group_key: str) -> list[dict]:
    """
    Вернуть участников группы с позицией.
    Формат: [{"user_id": int, "full_name": str, "username": str|None, "pos": int}, ...]
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        group_id = _resolve_group_id(cur, group_key)
        if group_id is None:
            return []

        cur.execute(
            """
            SELECT 
                m.user_id,
                COALESCE(
                    NULLIF(TRIM(CONCAT(u.first_name, ' ', u.last_name)), ''),
                    u.full_name,
                    u.display_name,
                    CAST(u.user_id AS TEXT)
                ) AS full_name,
                u.username,
                m.base_pos
            FROM time_group_members AS m
            LEFT JOIN users AS u ON u.user_id = m.user_id
            WHERE m.time_group_id = %s
            ORDER BY m.base_pos ASC, m.user_id ASC
            """,
            (group_id,),
        )
        res = []
        for user_id, full_name, username, pos in cur.fetchall() or []:
            res.append({
                "user_id": user_id,
                "full_name": (full_name or "").strip(),
                "username": username or None,
                "pos": int(pos) if pos is not None else 0,
            })
        return res

def _segment_starts_for_city(city: str):
    city = city.lower()
    if city == "vrn":   # Воронеж
        return (dtime(8,0), dtime(20,0))
    if city == "vdk":   # Владивосток (считаем по MSK)
        return (dtime(1,0), dtime(13,0))
    # по умолчанию как VRN
    return (dtime(8,0), dtime(20,0))

def detect_city_from_group(group_key: str) -> str:
    g = (group_key or "").lower()
    if g.startswith("vrn"): return "vrn"
    if g.startswith("vdk"): return "vdk"
    # по умолчанию как VRN
    return "vrn"

def segment_bounds_for_anchor(anchor_dt: datetime, city: str) -> tuple[datetime, datetime]:
    """Возвращает (segment_start, segment_end), где anchor_dt == segment_start."""
    t1, t2 = _segment_starts_for_city(city)
    start = anchor_dt
    # конец = следующий старт
    candidates = []
    for t in (t1, t2):
        cand = datetime.combine(anchor_dt.date(), t, tzinfo=MSK)
        if cand > anchor_dt:
            candidates.append(cand)
    if not candidates:
        # следующий день, первый старт
        candidates = [datetime.combine(anchor_dt.date()+timedelta(days=1), _segment_starts_for_city(city)[0], tzinfo=MSK)]
    end = min(candidates)
    # Ночной сегмент может уйти через полночь — это нормально, якорь остаётся на старте
    return start, end

def next_anchor_after(dt: datetime, group_key: str) -> datetime:
    """Ближайший будущий якорь (полный сегмент), без хвостов."""
    city = detect_city_from_group(group_key)
    t1, t2 = _segment_starts_for_city(city)
    base = dt.astimezone(MSK).date()
    candidates = [
        datetime.combine(base, t1, tzinfo=MSK),
        datetime.combine(base, t2, tzinfo=MSK),
        datetime.combine(base+timedelta(days=1), t1, tzinfo=MSK)
    ]
    for c in sorted(candidates):
        if c > dt:
            return c
    return datetime.combine(base+timedelta(days=1), t1, tzinfo=MSK)

def anchor_for_datetime(dt: datetime, group_key: str) -> datetime:
    """Находит старт сегмента, в который попадает dt (может быть сегодня/вчера по часам)."""
    city = detect_city_from_group(group_key)
    t1, t2 = _segment_starts_for_city(city)
    local = dt.astimezone(MSK)
    day0 = local.date()
    starts = sorted([
        datetime.combine(day0, t1, tzinfo=MSK),
        datetime.combine(day0, t2, tzinfo=MSK),
        datetime.combine(day0 - timedelta(days=1), t1, tzinfo=MSK),
        datetime.combine(day0 - timedelta(days=1), t2, tzinfo=MSK),
        datetime.combine(day0 + timedelta(days=1), t1, tzinfo=MSK),
    ])
    chosen = None
    for i in range(len(starts)-1):
        if starts[i] <= local < starts[i+1]:
            chosen = starts[i]
            break
    if chosen is None:
        chosen = starts[-2]  # крайний интервал
    return chosen
