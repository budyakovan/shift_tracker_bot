# -*- coding: utf-8 -*-
from datetime import time, date

_CLOCKS = {1:"🕐",2:"🕑",3:"🕒",4:"🕓",5:"🕔",6:"🕕",7:"🕖",8:"🕗",9:"🕘",10:"🕙",11:"🕚",12:"🕛"}
_CLOCKS_HALF = {1:"🕜",2:"🕝",3:"🕞",4:"🕟",5:"🕠",6:"🕡",7:"🕢",8:"🕣",9:"🕤",10:"🕥",11:"🕦",12:"🕧"}

def clock_emoji_by_time(t: time) -> str:
    h = (t.hour % 12) or 12
    return _CLOCKS_HALF[h] if t.minute >= 30 else _CLOCKS[h]

def clock_emoji_from_hhmm(s: str) -> str:
    """ s: 'HH:MM' """
    try:
        hh, mm = s.split(":")
        return clock_emoji_by_time(time(int(hh), int(mm)))
    except Exception:
        return "🕒"

_WEEKDAYS_RU = {0:"Понедельник",1:"Вторник",2:"Среда",3:"Четверг",4:"Пятница",5:"Суббота",6:"Воскресенье"}

def date_header_ru(d: date) -> str:
    return f"🗓 {_WEEKDAYS_RU.get(d.weekday(), d.strftime('%A'))}, {d.strftime('%Y-%m-%d')}"
