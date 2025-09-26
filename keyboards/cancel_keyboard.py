from telegram import ReplyKeyboardMarkup

def get_cancel_keyboard():
    """Клавиатура для отмены действий"""
    return ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)