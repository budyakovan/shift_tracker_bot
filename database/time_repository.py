import logging
from datetime import datetime, date
from .connection import db_connection
from database.group_repository import list_groups, list_users_in_group
from services.shift_calculator import ShiftCalculator

logger = logging.getLogger(__name__)
def list_group_users(group_key: str) -> list[dict]:
    """
    Вернёт участников группы с позицией.
    Формат: [{"user_id": int, "full_name": str, "username": str|None, "pos": int}, ...]
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        # получаем id группы по ключу
        cur.execute("SELECT id FROM time_groups WHERE key = %s", (group_key,))
        row = cur.fetchone()
        if not row:
            return []
        group_id = row[0]

        # выбираем участников
        cur.execute(
            """
            SELECT 
                tgu.user_id,
                COALESCE(u.full_name,
                         NULLIF(TRIM(CONCAT(u.first_name, ' ', u.last_name)), ''),
                         u.display_name,
                         CAST(u.user_id AS TEXT)) AS full_name,
                u.username,
                tgu.pos
            FROM time_group_users AS tgu
            LEFT JOIN users AS u ON u.id = tgu.user_id
            WHERE tgu.group_id = %s
            ORDER BY tgu.pos ASC, tgu.user_id ASC
            """,
            (group_id,),
        )
        res = []
        for user_id, full_name, username, pos in cur.fetchall():
            res.append({
                "user_id": user_id,
                "full_name": full_name or "",
                "username": username or None,
                "pos": pos if pos is not None else 0,
            })
        return res


def delete_time_group(group_key: str) -> bool:
    """Удалить тайм-группу по ключу. Возвращает True, если что-то удалилось."""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM time_groups WHERE key = %s",
            (group_key,),
        )
        return cur.rowcount > 0

def delete_time_profile(profile_key: str) -> bool:
    """Удалить тайм-профиль по ключу.
    Работает только если нет связанных групп (time_groups).
    Возвращает True, если профиль удалён.
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "DELETE FROM time_profiles WHERE key = %s",
                (profile_key,),
            )
            return cur.rowcount > 0
        except Exception as e:
            # например, ForeignKey violation из-за связанных групп
            raise e

def create_profile(key: str, name: str, tz_name: str = None, tz_offset_hours: int = 0):
    """Создать профиль времени"""
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
    """Вернуть список всех профилей времени"""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT key, name, tz_name, tz_offset_hours
            FROM time_profiles
            ORDER BY name
            """
        )
        rows = cur.fetchall()
        return [
            {"key": r[0], "name": r[1], "tz_name": r[2], "tz_offset_hours": r[3]}
            for r in rows
        ]

def add_slot(profile_key: str, pos: int, start: str, end: str, name: str = None):
    """Добавить слот в профиль времени"""
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

def clear_profile_slots(profile_key: str):
    """Очистить все слоты профиля"""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM time_profile_slots
            WHERE profile_id = (SELECT id FROM time_profiles WHERE key = %s)
            """,
            (profile_key,),
        )
        return cur.rowcount

def add_user_to_group(group_key: str, user_id: int, base_pos: int):
    """Добавить пользователя в тайм-группу"""
    with db_connection.connect() as conn, conn.cursor() as cur:
        sql = """
        INSERT INTO time_group_members (time_group_id, user_id, base_pos)
        SELECT tg.id, %s, %s
        FROM time_groups tg
        WHERE tg.key = %s
        ON CONFLICT (time_group_id, user_id) DO UPDATE
            SET base_pos = EXCLUDED.base_pos
        """
        cur.execute(sql, (user_id, base_pos, group_key))
        return cur.rowcount > 0

def remove_user_from_group(group_key: str, user_id: int):
    """Удалить пользователя из тайм-группы"""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM time_group_members
            WHERE time_group_id = (SELECT id FROM time_groups WHERE key = %s)
              AND user_id = %s
            """,
            (group_key, user_id),
        )
        return cur.rowcount > 0

def list_groups():
    """Вернуть список всех тайм-групп"""
    with db_connection.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT tg.key, tg.name, tp.key AS profile_key, tg.epoch,
                   tg.rotation_period_days, tg.rotation_dir, tg.tz_name, tg.tz_offset_hours
            FROM time_groups tg
            JOIN time_profiles tp ON tg.profile_id = tp.id
            ORDER BY tg.name
            """
        )
        rows = cur.fetchall()
        return [
            {
                "key": r[0],
                "name": r[1],
                "profile_key": r[2],
                "epoch": r[3],
                "period": r[4],
                "rotation_dir": r[5],
                "tz_name": r[6],
                "tz_offset_hours": r[7],
            }
            for r in rows
        ]

def get_group_info(group_key: str):
    """
    Вернуть подробную информацию по тайм-группе:
    {
      key, name, profile_key, epoch, period, rotation_dir, tz_name, tz_offset_hours,
      members: [{user_id, base_pos, username, first_name, last_name}, ...],
      slots:   [{pos, name, start_time, end_time}, ...]
    }
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        # 1) Основная информация по группе
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
            return None

        group_id = row[0]
        info = {
            "key": row[1],
            "name": row[2],
            "profile_key": row[3],
            "epoch": row[4],
            "period": row[5],
            "rotation_dir": row[6],
            "tz_name": row[7],
            "tz_offset_hours": row[8],
            "members": [],
            "slots": [],
        }

        # 2) Участники группы
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
            ORDER BY m.base_pos, COALESCE(u.first_name,'') , COALESCE(u.last_name,''), COALESCE(u.username,''), m.user_id::text
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

        # 3) Слоты профиля (для удобного отображения в /admin_tg_show)
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
            # t может быть datetime.time или строка; приводим к HH:MM
            try:
                return t.strftime("%H:%M")
            except Exception:
                return str(t)[:5]  # на всякий случай

        info["slots"] = [
            {
                "pos": r[0],
                "name": r[1] or "",
                "start": _fmt(r[2]),
                "end": _fmt(r[3]),
                # оставим и старые ключи на совместимость, вдруг где-то еще нужны
                "start_time": r[2],
                "end_time": r[3],
            }
            for r in slots
        ]

        return info

def set_group_tz(group_key: str, tz_name: str) -> bool:
    """Установить IANA-часовой пояс для тайм-группы.
       Пример tz_name: 'Europe/Moscow', 'Asia/Vladivostok'.
       Возвращает True, если обновлена хотя бы одна строка.
    """
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
    """
    Установить период ротации (в днях) для тайм-группы.
    days >= 0. Значение 0 = без ротации (фиксированное назначение).
    Возвращает True, если обновлена хотя бы одна строка.
    """
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

def get_profile_info(profile_key: str):
    """
    Вернёт словарь с информацией о профиле времени и его слотах.

    Структура:
    {
      "key": str,
      "name": str|None,
      "tz_name": str|None,
      "slots": [
        {"pos": int, "start": "HH:MM", "end": "HH:MM", "name": str|None},
        ...
      ]
    }
    """
    with db_connection.connect() as conn, conn.cursor() as cur:
        # 1) Находим сам профиль и его id
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
        profile = {
            "key": key,
            "name": name,
            "tz_name": tz_name,
            "slots": [],
        }

        # 2) Тянем слоты по profile_id (а не по profile_key!)
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

def update_name(key: str, new_name: str) -> bool:
    if not key or not new_name:
        return False

    with db_connection.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE {TABLE} SET name = %s WHERE key = %s", (new_name.strip(), key.strip().lower()))
        conn.commit()
        return cur.rowcount > 0

def create_time_group(
    group_key: str,
    profile_key: str,
    epoch,                     # str | datetime.date | datetime.datetime
    period_days: int,
    rotation_dir: int = 1,
    tz_name: str | None = None,   # игнорируем, tz берём из профиля
    name: str | None = None,      # ✅ НОВОЕ: «человеческое» имя группы
):
    """Создать/обновить тайм-группу. Часовой пояс ВСЕГДА наследуем от профиля."""
    # --- нормализация epoch ---
    if isinstance(epoch, date):
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
                epoch_date = date(date.today().year, int(m), int(d))
            except Exception as e:
                raise ValueError(f"Неверный формат даты epoch: {epoch!r}") from e
    else:
        raise TypeError(f"epoch должен быть str или date, получено: {type(epoch).__name__}")

    with db_connection.connect() as conn, conn.cursor() as cur:
        # 1) получаем профиль
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

        # ✅ имя группы: предпочтение явному name; иначе можно взять profile_name; fallback — group_key
        group_name = (name or profile_name or group_key).strip()

        # 2) upsert группы, tz берём из профиля
        cur.execute(
            """
            INSERT INTO time_groups
                (key,  name,       profile_id, epoch, rotation_period_days, rotation_dir, tz_name,      tz_offset_hours)
            VALUES
                (%s,   %s,         %s,         %s,    %s,                   %s,          %s,            %s)
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
                prof_tz_name,       # из профиля
                prof_tz_offset,     # из профиля
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Не удалось создать/обновить тайм-группу (RETURNING не вернул id)")
        return row[0]