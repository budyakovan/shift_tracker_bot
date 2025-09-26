# handlers/absence_banner.py
# -*- coding: utf-8 -*-
import re
from datetime import datetime
from typing import Tuple
from telegram.constants import ParseMode
from database.absence_repository import get_absence_on_date

DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

def inject_absence_banner_for_text(raw_text: str, user_id: int) -> Tuple[str, bool]:
    """
    Возвращает (текст_с_возможным_баннером, использован_html_баннер).
    Баннер добавляется только если день попадает в отпуск/больничный.
    """
    if not raw_text:
        return raw_text, False

    m = DATE_RE.search(raw_text)
    if not m:
        return raw_text, False

    try:
        target_date = datetime.strptime(m.group(0), "%Y-%m-%d").date()
    except Exception:
        return raw_text, False

    absence = get_absence_on_date(user_id, target_date)
    if not absence:
        return raw_text, False

    emoji = "🏖" if absence["absence_type"] == "vacation" else "🤒"
    label = "Отпуск" if absence["absence_type"] == "vacation" else "Больничный"
    banner = (
        f"<b>{emoji} {label}</b>: {absence['date_from']}—{absence['date_to']}"
        + (f" — {absence['comment']}" if absence.get("comment") else "")
        + "\n⚠️ <b>День попадает в отсутствие</b>\n"
    )
    return banner + raw_text, True

async def reply_with_absence_banner(update, text: str, user_id: int):
    """
    Всегда отправляем parse_mode=HTML, потому что исходные тексты уже содержат <b>, <code> и т.п.
    Если отсутствия нет — просто отправим исходный текст как HTML.
    """
    new_text, _ = inject_absence_banner_for_text(text, user_id)
    await update.message.reply_text(new_text, parse_mode=ParseMode.HTML)
