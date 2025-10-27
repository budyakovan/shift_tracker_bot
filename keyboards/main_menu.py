from telegram import ReplyKeyboardMarkup

def get_main_keyboard():
    """Главное меню клавиатуры"""
    return ReplyKeyboardMarkup([
        ['📅 График', '🏢 Локации'],
        ['❓ Помощь']
    ], resize_keyboard=True)

def get_cancel_keyboard():
    """Клавиатура для отмены действий"""
    return ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)