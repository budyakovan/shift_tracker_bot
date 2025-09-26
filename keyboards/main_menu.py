from telegram import ReplyKeyboardMarkup

def get_main_keyboard():
    """Главное меню клавиатуры"""
    return ReplyKeyboardMarkup([
        ['/next', '/my_next'],
        ['➕ Новый график', '📋 Мои графики'],
        ['❓ Помощь']
    ], resize_keyboard=True)

def get_cancel_keyboard():
    """Клавиатура для отмены действий"""
    return ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)