import os
import secrets
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


class Config:
    # Database
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_NAME = os.getenv('DB_NAME', 'mybotdb')
    DB_USER = os.getenv('DB_USER', 'shift_tracker_bot')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_PORT = os.getenv('DB_PORT', '5432')

    # Bot
    BOT_TOKEN = os.getenv('BOT_TOKEN', '')

    # Default settings
    DEFAULT_EPOCH_DATE = os.getenv('DEFAULT_EPOCH_DATE', '2025-08-28')
    DEFAULT_SCHEDULE = os.getenv('DEFAULT_SCHEDULE', 'стандартный')

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # Security
    SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(32))

    # Admin settings
    DEFAULT_ADMIN_IDS = [int(x) for x in os.getenv('DEFAULT_ADMIN_IDS', '').split(',') if x]

    # чат для мониторинга AFK
    #WORK_CHAT_ID = -1003096721091  # ID суперчата
    #WORK_TOPIC_ID = 9  # ID темы внутри чата "Рабочий график"
    #WORK_TOPIC_TITLE = "Рабочий график"  # опционально, только для информации


# Проверяем обязательные переменные
if not Config.BOT_TOKEN:
    print("⚠️  Внимание: BOT_TOKEN не найден в .env файле")

config = Config()