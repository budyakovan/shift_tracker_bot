# database/connection.py
import psycopg2
import logging
from config import config

logger = logging.getLogger(__name__)

class DatabaseConnection:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # ленивое подключение
        self.connection = None

    def connect(self):
        """
        Создаёт и/или возвращает текущее соединение с БД.
        ДОЛЖНО возвращать объект psycopg2 connection (НЕ None).
        """
        # если соединение уже открыто и живо — вернуть
        if self.connection and getattr(self.connection, "closed", 1) == 0:
            return self.connection

        # иначе открыть новое
        try:
            self.connection = psycopg2.connect(
                host=config.DB_HOST,
                database=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                port=config.DB_PORT,
            )
            self.connection.autocommit = True
            logger.info("✅ Подключение к БД установлено")
            return self.connection  # <-- ВАЖНО: явно вернуть conn
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД: {e}")
            self.connection = None
            raise

    def get_connection(self):
        """Синоним для connect(), оставлен для читаемости."""
        return self.connect()

    def reconnect(self):
        try:
            if self.connection and getattr(self.connection, "closed", 1) == 0:
                self.connection.close()
            self.connection = None
            return self.connect()
        except Exception as e:
            logger.error(f"❌ Не удалось восстановить соединение: {e}")
            raise

    def close(self):
        if self.connection and getattr(self.connection, "closed", 1) == 0:
            self.connection.close()
            logger.info("🔌 Соединение с БД закрыто")

db_connection = DatabaseConnection()

# Хелперы для безопасного восстановления после ошибок
def safe_rollback(conn):
    """На случай, если где-то отключат autocommit и словят ошибку."""
    try:
        if conn and not conn.autocommit:
            conn.rollback()
    except Exception:
        pass

def is_tx_aborted_error(exc: Exception) -> bool:
    return "current transaction is aborted" in str(exc).lower()
