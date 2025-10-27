# /home/telegrambot/shift_tracker_bot/database/connection.py
import psycopg2
import logging
from config import config

# Этот файл отвечает за управление подключением к базе данных PostgreSQL.
# Здесь реализован паттерн Singleton для работы с одним глобальным соединением
# к базе данных во всём приложении (чтобы не создавать новые соединения каждый раз).
# Основные возможности:
# - Ленивое подключение к БД (создаётся только при первом обращении).
# - Автоматическая установка autocommit для удобства работы.
# - Методы для повторного подключения (reconnect) и корректного закрытия соединения.
# - Хелперы для обработки ошибок транзакций и безопасного отката.

import psycopg2
import logging
from config import config

logger = logging.getLogger(__name__)

class DatabaseConnection:
    _instance = None  # хранит единственный экземпляр соединения (Singleton)

    def __new__(cls):
        # проверка, создан ли уже объект; если нет — создаём и инициализируем
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # ленивое подключение — пока connection = None
        self.connection = None

    def connect(self):
        """
        Создаёт и/или возвращает текущее соединение с БД.
        ДОЛЖНО возвращать объект psycopg2 connection (НЕ None).
        """
        # если соединение уже открыто и активно — вернуть его
        if self.connection and getattr(self.connection, "closed", 1) == 0:
            return self.connection

        # иначе открыть новое соединение
        try:
            self.connection = psycopg2.connect(
                host=config.DB_HOST,
                database=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                port=config.DB_PORT,
            )
            self.connection.autocommit = True  # включаем autocommit
            logger.info("✅ Подключение к БД установлено")
            return self.connection
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД: {e}")
            self.connection = None
            raise

    def get_connection(self):
        """Синоним для connect(), оставлен для читаемости кода."""
        return self.connect()

    def reconnect(self):
        """Закрыть текущее соединение и открыть новое."""
        try:
            if self.connection and getattr(self.connection, "closed", 1) == 0:
                self.connection.close()
            self.connection = None
            return self.connect()
        except Exception as e:
            logger.error(f"❌ Не удалось восстановить соединение: {e}")
            raise

    def close(self):
        """Закрыть соединение с БД, если оно активно."""
        if self.connection and getattr(self.connection, "closed", 1) == 0:
            self.connection.close()
            logger.info("🔌 Соединение с БД закрыто")

# глобальный объект подключения для всего проекта
db_connection = DatabaseConnection()

# ---------------- Хелперы ---------------- #

def safe_rollback(conn):
    """На случай, если где-то отключат autocommit и произойдёт ошибка транзакции."""
    try:
        if conn and not conn.autocommit:
            conn.rollback()
    except Exception:
        pass

def is_tx_aborted_error(exc: Exception) -> bool:
    """Проверка, что ошибка связана с 'current transaction is aborted'."""
    return "current transaction is aborted" in str(exc).lower()
