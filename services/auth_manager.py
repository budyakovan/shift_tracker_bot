# services/auth_manager.py
# -*- coding: utf-8 -*-
import logging
from typing import Optional

from database import user_repository
from services.user_manager import user_manager
from database.connection import db_connection
from config import config

logger = logging.getLogger(__name__)

USER_ROLE_USER = "user"
USER_ROLE_ADMIN = "admin"

class AuthManager:
    def __init__(self):
        self.user_repo = user_repository

    # --- helpers ---
    def _owner_or_config_admin(self, user_id: int) -> bool:
        try:
            ids = set()
            owner_id = getattr(config, "OWNER_ID", None)
            if owner_id:
                ids.add(int(owner_id))
            cfg_admins = getattr(config, "ADMIN_IDS", []) or []
            ids.update(int(x) for x in cfg_admins if x)
            return int(user_id) in ids
        except Exception:
            return False

    def _db_has_column(self, conn, table: str, column: str) -> bool:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name=%s AND column_name=%s
                LIMIT 1
            """, (table, column))
            return cur.fetchone() is not None

    def _ensure_role_row(self, conn, role_name: str) -> int:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM user_roles WHERE name=%s LIMIT 1", (role_name,))
            row = cur.fetchone()
            if row:
                return int(row[0])
            cur.execute("INSERT INTO user_roles (name) VALUES (%s) RETURNING id", (role_name,))
            return int(cur.fetchone()[0])

    def _set_users_role_text_if_exists(self, conn, user_id: int, role: str) -> None:
        if not self._db_has_column(conn, "users", "role"):
            return
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role=%s WHERE user_id=%s", (role, user_id))

    def _set_user_settings_role(self, conn, user_id: int, role_id: int) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_settings SET role_id=%s, updated_at=NOW() WHERE user_id=%s",
                (role_id, user_id)
            )
            if cur.rowcount == 0:
                cur.execute("""
                    INSERT INTO user_settings (user_id, role_id, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET role_id=EXCLUDED.role_id, updated_at=NOW()
                """, (user_id, role_id))

    def _log_admin_action(self, conn, admin_id: int, action_type: str, target_user_id: int, details_json: str) -> None:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM information_schema.tables
                WHERE table_schema='public' AND table_name='admin_actions' LIMIT 1
            """)
            if cur.fetchone() is None:
                return
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO admin_actions (admin_id, action_type, target_user_id, details)
                VALUES (%s, %s, %s, %s)
            """, (admin_id, action_type, target_user_id, details_json))

    # --- public API ---
    def register_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> bool:
        try:
            return self.user_repo.create_user(user_id, username, first_name, last_name)
        except Exception as e:
            logger.error(f"Error registering user: {e}")
            return False

    def is_user_approved(self, user_id: int) -> bool:
        try:
            user = self.user_repo.get_user(user_id)
            return bool(user and user.get('is_approved', False))
        except Exception as e:
            logger.error(f"Error checking user approval: {e}")
            return False

    def is_admin(self, user_id: int) -> bool:
        try:
            # 0) Конфиговые суперпользователи — сразу True
            if self._owner_or_config_admin(user_id):
                return True

            # 1) Быстрый кэш/слой user_manager (если есть)
            try:
                if user_manager.is_user_admin(user_id):
                    return True
            except Exception:
                pass

            # 2) Читаем из БД c автопочинкой/ретраем
            conn = db_connection.get_connection()

            for attempt in (1, 2):
                try:
                    # (а) users.role (текстовая роль)
                    if self._db_has_column(conn, "users", "role"):
                        with conn.cursor() as cur:
                            cur.execute("SELECT role FROM users WHERE user_id=%s LIMIT 1", (user_id,))
                            row = cur.fetchone()
                            if row and str(row[0]).lower() == USER_ROLE_ADMIN:
                                return True

                    # (б) user_settings.role_id → user_roles.name
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT ur.name
                            FROM user_settings us
                            JOIN user_roles ur ON ur.id = us.role_id
                            WHERE us.user_id = %s
                            LIMIT 1
                        """, (user_id,))
                        row = cur.fetchone()
                        if row and str(row[0]).lower() == USER_ROLE_ADMIN:
                            return True

                    # если дошли сюда — админ не найден
                    return False

                except Exception as e:
                    # Починка "aborted" соединения и повтор
                    from database.connection import safe_rollback, is_tx_aborted_error
                    logger.error("is_admin attempt %s failed: %s", attempt, e)
                    safe_rollback(conn)
                    if is_tx_aborted_error(e):
                        try:
                            conn = db_connection.reconnect()
                        except Exception:
                            # если не получилось переподключиться — выходим
                            break
                    # и даём второй шанс циклом

        except Exception as e:
            logger.error(f"is_admin error: {e}")

        return False

    def authorize_user(self, user_id: int, required_role: str = USER_ROLE_USER) -> bool:
        try:
            if required_role == USER_ROLE_ADMIN:
                return self.is_admin(user_id)
            if not self.is_user_approved(user_id):
                return False
            if self.is_admin(user_id):
                return True
            user = self.user_repo.get_user(user_id)
            if not user:
                return False
            role = (user.get('role') or '').lower()
            return role in (USER_ROLE_USER, USER_ROLE_ADMIN)
        except Exception as e:
            logger.error(f"Authorization error: {e}")
            return False

    def approve_user(self, target_user_id: int, admin_id: int) -> bool:
        if not self.authorize_user(admin_id, USER_ROLE_ADMIN):
            return False
        try:
            return self.user_repo.approve_user(target_user_id, admin_id)
        except Exception as e:
            logger.error(f"Approve user error: {e}")
            return False

    def get_pending_users(self) -> list:
        try:
            return self.user_repo.get_pending_users()
        except Exception as e:
            logger.error(f"Error getting pending users: {e}")
            return []

    def promote_to_admin(self, target_user_id: int, admin_id: int) -> bool:
        if not self.authorize_user(admin_id, USER_ROLE_ADMIN):
            return False
        conn = db_connection.get_connection()
        try:
            role_id = self._ensure_role_row(conn, USER_ROLE_ADMIN)
            self._set_user_settings_role(conn, target_user_id, role_id)
            self._set_users_role_text_if_exists(conn, target_user_id, USER_ROLE_ADMIN)
            self._log_admin_action(conn, admin_id, 'promote_to_admin', target_user_id, '{"action":"promote"}')
            conn.commit()
            return True
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logger.error(f"Promote to admin error: {e}")
            return False

    def demote_from_admin(self, target_user_id: int, admin_id: int) -> bool:
        if not self.authorize_user(admin_id, USER_ROLE_ADMIN):
            return False
        conn = db_connection.get_connection()
        try:
            role_id = self._ensure_role_row(conn, USER_ROLE_USER)
            self._set_user_settings_role(conn, target_user_id, role_id)
            self._set_users_role_text_if_exists(conn, target_user_id, USER_ROLE_USER)
            self._log_admin_action(conn, admin_id, 'demote_from_admin', target_user_id, '{"action":"demote"}')
            conn.commit()
            return True
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logger.error(f"Demote from admin error: {e}")
            return False

auth_manager = AuthManager()
