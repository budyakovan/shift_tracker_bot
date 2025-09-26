import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from .connection import db_connection

logger = logging.getLogger(__name__)

# Простые константы для ролей
USER_ROLE_USER = "user"
USER_ROLE_ADMIN = "admin"


class UserRepository:
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получает полную информацию о пользователе"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    SELECT us.user_id, ur.name as role_name, us.is_approved
                    FROM user_settings us
                    LEFT JOIN user_roles ur ON us.role_id = ur.id
                    WHERE us.user_id = %s
                """, (user_id,))
                result = cursor.fetchone()

                if result:
                    return {
                        'user_id': result[0],
                        'role': result[1] if result[1] else USER_ROLE_USER,
                        'is_approved': result[2] if result[2] else False
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None

    def create_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> bool:
        """Создает нового пользователя или обновляет его данные"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                # Сохраняем в таблицу users
                cursor.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        updated_at = NOW()
                """, (user_id, username, first_name, last_name))

                # Получаем ID роли user
                cursor.execute("SELECT id FROM user_roles WHERE name = %s", (USER_ROLE_USER,))
                role_id = cursor.fetchone()[0]

                # Создаем запись в user_settings (если нет)
                cursor.execute("""
                    INSERT INTO user_settings (user_id, role_id, epoch_date, is_approved)
                    VALUES (%s, %s, NOW(), %s)
                    ON CONFLICT (user_id) DO NOTHING
                """, (user_id, role_id, False))

                db_connection.get_connection().commit()
                return True
        except Exception as e:
            db_connection.get_connection().rollback()
            logger.error(f"Error creating user: {e}")
            return False

    def remove_user(self, user_id: int) -> bool:
        """
        Удаляет пользователя «чисто»:
        - зануляет admin_id в admin_actions, где этот пользователь выступал админом,
        - удаляет записи admin_actions, где он был целевым пользователем (на случай отсутствия CASCADE),
        - удаляет его из user_settings и users.
        """
        conn = db_connection.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    # 1) если пользователь когда-то был админом действия — зануляем ссылку
                    cur.execute("UPDATE admin_actions SET admin_id = NULL WHERE admin_id = %s;", (user_id,))
                    # 2) удаляем действия, направленные на этого пользователя (подстраховка, если нет CASCADE)
                    cur.execute("DELETE FROM admin_actions WHERE target_user_id = %s;", (user_id,))
                    # 3) основной профиль
                    cur.execute("DELETE FROM user_settings WHERE user_id = %s;", (user_id,))
                    # 4) карточка пользователя
                    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
            return True
        except Exception as e:
            logger.error(f"Error removing user: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return False

    def approve_user(self, user_id: int, admin_id: int) -> bool:
        """Одобряет пользователя"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    UPDATE user_settings 
                    SET is_approved = TRUE, updated_at = NOW()
                    WHERE user_id = %s
                """, (user_id,))

                # Логируем действие
                cursor.execute("""
                    INSERT INTO admin_actions (admin_id, action_type, target_user_id, details)
                    VALUES (%s, %s, %s, %s)
                """, (admin_id, 'user_approval', user_id, '{"action": "approve"}'))

                db_connection.get_connection().commit()
                return True
        except Exception as e:
            db_connection.get_connection().rollback()
            logger.error(f"Error approving user: {e}")
            return False

    def get_pending_users(self) -> List[Dict]:
        """Получает список неодобренных пользователей"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        us.user_id, 
                        us.created_at,
                        u.username,
                        u.first_name,
                        u.last_name
                    FROM user_settings us
                    LEFT JOIN users u ON us.user_id = u.user_id
                    WHERE us.is_approved = FALSE
                    ORDER BY us.created_at DESC
                """)

                return [
                    {
                        'user_id': row[0],
                        'created_at': row[1],
                        'username': row[2],
                        'first_name': row[3],
                        'last_name': row[4]
                    }
                    for row in cursor.fetchall()
                ]
        except Exception as e:
            logger.error(f"Error getting pending users: {e}")
            return []

    def get_all_users(self) -> List[Dict]:
        """Получает список всех пользователей"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        us.user_id, 
                        ur.name as role_name, 
                        us.is_approved,
                        us.created_at,
                        us.updated_at,
                        u.username,
                        u.first_name,
                        u.last_name
                    FROM user_settings us
                    LEFT JOIN user_roles ur ON us.role_id = ur.id
                    LEFT JOIN users u ON us.user_id = u.user_id
                    ORDER BY us.created_at DESC
                """)

                return [
                    {
                        'user_id': row[0],
                        'role': row[1] if row[1] else USER_ROLE_USER,
                        'is_approved': row[2],
                        'created_at': row[3],
                        'updated_at': row[4],
                        'username': row[5],
                        'first_name': row[6],
                        'last_name': row[7]
                    }
                    for row in cursor.fetchall()
                ]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []

    def create_user_schedule(self, user_id: int, name: str, description: str = None) -> int:
        """Создает пользовательский график"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_custom_schedules (user_id, name, description)
                    VALUES (%s, %s, %s) RETURNING id
                """, (user_id, name, description))
                schedule_id = cursor.fetchone()[0]
                db_connection.get_connection().commit()
                return schedule_id
        except Exception as e:
            db_connection.get_connection().rollback()
            logger.error(f"Error creating user schedule: {e}")
            raise

    def get_user_schedules(self, user_id: int) -> List[Dict]:
        """Получает все графики пользователя"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                # Стандартные графики
                cursor.execute("SELECT id, name, description FROM work_schedules ORDER BY id")
                standard_schedules = [
                    {'id': row[0], 'name': row[1], 'description': row[2], 'type': 'standard'}
                    for row in cursor.fetchall()
                ]

                # Пользовательские графики
                cursor.execute("""
                    SELECT id, name, description 
                    FROM user_custom_schedules 
                    WHERE user_id = %s AND is_active = TRUE
                    ORDER BY created_at
                """, (user_id,))
                custom_schedules = [
                    {'id': row[0], 'name': row[1], 'description': row[2], 'type': 'custom'}
                    for row in cursor.fetchall()
                ]

                return standard_schedules + custom_schedules
        except Exception as e:
            logger.error(f"Error getting user schedules: {e}")
            return []

    def is_user_admin(self, user_id: int) -> bool:
        """
        Возвращает True, если у пользователя роль admin (без учета регистра).
        Читает user_settings.role_id -> user_roles.name.
        """
        conn = db_connection.get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ur.name
                FROM user_settings us
                JOIN user_roles ur ON ur.id = us.role_id
                WHERE us.user_id = %s
                LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return False
            return str(row[0]).strip().lower() == "admin"

    def update_all_users(self) -> int:
        """
        Нормализует username/имена в таблице users:
          - убирает ведущий '@' у username
          - подрезает пробелы у first_name/last_name
          - пустые строки превращает в NULL
        Возвращает количество реально обновлённых строк.
        """
        try:
            conn = db_connection.get_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        WITH prepared AS (
                            SELECT
                                u.user_id,
                                NULLIF(REGEXP_REPLACE(COALESCE(u.username, ''), '^\s*@', ''), '')      AS new_username,
                                NULLIF(BTRIM(COALESCE(u.first_name, '')), '')                           AS new_first_name,
                                NULLIF(BTRIM(COALESCE(u.last_name,  '')), '')                           AS new_last_name
                            FROM users u
                        ),
                        diffs AS (
                            SELECT u.user_id, p.new_username, p.new_first_name, p.new_last_name
                            FROM users u
                            JOIN prepared p USING(user_id)
                            WHERE (u.username   IS DISTINCT FROM p.new_username)
                               OR (u.first_name IS DISTINCT FROM p.new_first_name)
                               OR (u.last_name  IS DISTINCT FROM p.new_last_name)
                        )
                        UPDATE users u
                        SET username   = d.new_username,
                            first_name = d.new_first_name,
                            last_name  = d.new_last_name,
                            updated_at = NOW()
                        FROM diffs d
                        WHERE u.user_id = d.user_id
                        RETURNING u.user_id
                    """)
                    changed = cur.rowcount or 0
            return changed
        except Exception as e:
            logger.error(f"Error updating all users: {e}")
            return 0

class ShiftRepository:
    def get_shift_settings(self, schedule_id: int, schedule_type: str = 'standard') -> Dict:
        """Получает настройки смен для графика"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                if schedule_type == 'standard':
                    cursor.execute("""
                        SELECT st.name, ss.start_time, ss.end_time, ss.description
                        FROM schedule_settings ss
                        JOIN shift_types st ON ss.shift_type_id = st.id
                        WHERE ss.schedule_id = %s
                    """, (schedule_id,))
                else:
                    cursor.execute("""
                        SELECT st.name, uss.start_time, uss.end_time, uss.description
                        FROM user_schedule_settings uss
                        JOIN shift_types st ON uss.shift_type_id = st.id
                        WHERE uss.schedule_id = %s
                    """, (schedule_id,))

                settings = {}
                for row in cursor.fetchall():
                    settings[row[0]] = {
                        'start_time': row[1],
                        'end_time': row[2],
                        'description': row[3]
                    }
                return settings
        except Exception as e:
            logger.error(f"Error getting shift settings: {e}")
            return {}


class ScheduleRepository:
    def get_all_schedules(self) -> List[Dict]:
        """Получает все активные графики"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    SELECT id, name, description 
                    FROM work_schedules 
                    WHERE is_active = TRUE
                    ORDER BY name
                """)

                results = cursor.fetchall()
                print(f"DEBUG: Schedules from DB: {results}")  # ← ДОБАВЬТЕ ЭТУ СТРОКУ

                return [
                    {'id': row[0], 'name': row[1], 'description': row[2]}
                    for row in results
                ]
        except Exception as e:
            logger.error(f"Error getting schedules: {e}")
            return []

    def create_schedule(self, name: str, description: str = None) -> int:
        """Создает новый график"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    INSERT INTO work_schedules (name, description)
                    VALUES (%s, %s) RETURNING id
                """, (name, description))
                schedule_id = cursor.fetchone()[0]
                db_connection.get_connection().commit()
                return schedule_id
        except Exception as e:
            db_connection.get_connection().rollback()
            logger.error(f"Error creating schedule: {e}")
            raise

    def update_schedule(self, schedule_id: int, name: str, description: str = None) -> bool:
        """Обновляет график"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    UPDATE work_schedules 
                    SET name = %s, description = %s
                    WHERE id = %s
                """, (name, description, schedule_id))
                db_connection.get_connection().commit()
                return cursor.rowcount > 0
        except Exception as e:
            db_connection.get_connection().rollback()
            logger.error(f"Error updating schedule: {e}")
            return False

    def delete_schedule(self, schedule_id: int) -> bool:
        """Удаляет график (soft delete)"""
        try:
            with db_connection.get_connection().cursor() as cursor:
                cursor.execute("""
                    UPDATE work_schedules 
                    SET is_active = FALSE
                    WHERE id = %s
                """, (schedule_id,))
                db_connection.get_connection().commit()
                return cursor.rowcount > 0
        except Exception as e:
            db_connection.get_connection().rollback()
            logger.error(f"Error deleting schedule: {e}")
            return False

