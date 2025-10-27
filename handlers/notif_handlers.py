# /home/telegrambot/shift_tracker_bot/handlers/notif_handlers.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
from typing import Optional, Tuple
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler
from html import escape

from config import config
from database import time_repository as time_repo
from database.notif_repository import (
    set_target, get_target, list_targets, clear_target, resolve_target,
)

logger = logging.getLogger(__name__)

# ==== helpers ==================================================================

def _parse_args(args: list[str]) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int], Optional[str]]:
    """
    Разбор аргументов для /admin_notif_set:
      /admin_notif_set <group_key> [kind] [chat_id] [topic_id]
    Возвращает (group_key, kind, chat_id, topic_id, err)
    Возвращает (group_key, kind, chat_id, topic_id, err)
    """
    if not args:
        return None, None, None, None, "ожидаю: /admin_notif_set <group_key> [kind] [chat_id] [topic_id]"

    group_key = args[0].strip()
    kind: Optional[str] = None
    chat_id: Optional[int] = None
    topic_id: Optional[int] = None

    if len(args) >= 2:
        # Может быть kind, а может быть сразу chat_id
        a1 = args[1].strip().lower()
        if a1.lstrip("-").isdigit():
            chat_id = int(a1)
        else:
            kind = a1

    if len(args) >= 3:
        if chat_id is None:
            # Тогда это chat_id
            chat_id = int(args[2])
        else:
            # Тогда это topic_id
            topic_id = int(args[2])

    if len(args) >= 4:
        topic_id = int(args[3])

    return group_key, (kind or "general"), chat_id, topic_id, None


async def _reply_ok(update: Update, text: str):
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def _reply_err(update: Update, text: str):
    await update.message.reply_text("❌ " + text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def _send_to_target(context: ContextTypes.DEFAULT_TYPE,
                          chat_id: int,
                          topic_id: Optional[int],
                          text: str,
                          parse_mode: Optional[str] = ParseMode.HTML):
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            message_thread_id=topic_id if topic_id else None,
            disable_web_page_preview=True
        )
    except Exception:
        logger.exception("Failed to send test notification to chat_id=%s topic_id=%s", chat_id, topic_id)


# ==== commands ================================================================

async def admin_notif_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_notif_set <group_key> [kind] [chat_id] [topic_id]
    Если chat_id/topic_id опущены — берём их из текущего сообщения.
    kind по умолчанию: general.

    Дополнительно: всегда создаём/обновляем привязку kind='listen' для этой группы,
    чтобы бот "слушал" триггеры (ушёл/отошёл и т.п.) только в указанном чате/топике.
    """
    group_key, kind, chat_id_arg, topic_id_arg, err = _parse_args(context.args or [])
    if err:
        await _reply_err(update, err)
        return

    # валидация группы
    try:
        groups = time_repo.list_groups() or []
        known = {str(g.get("key")) for g in groups}
    except Exception:
        known = set()
        logger.exception("time_repo.list_groups failed")

    if known and group_key not in known:
        await _reply_err(update, f"Неизвестная группа <code>{escape(group_key)}</code>.")
        return

    # подставляем chat/topic из текущего сообщения, если не передали
    if chat_id_arg is None:
        chat_id_arg = update.effective_chat.id
    if topic_id_arg is None:
        topic_id_arg = getattr(update.effective_message, "message_thread_id", None)

    # 1) основная привязка — выбранный kind (по умолчанию general)
    rec_main = set_target(
        group_key=group_key,
        kind=kind,
        chat_id=chat_id_arg,
        topic_id=topic_id_arg
    )

    # 2) дополнительно — привязка "слушать" (kind='listen') в том же месте
    rec_listen = set_target(
        group_key=group_key,
        kind="listen",
        chat_id=chat_id_arg,
        topic_id=topic_id_arg
    )

    ttopic_main = f", topic_id=<code>{rec_main['topic_id']}</code>" if rec_main["topic_id"] is not None else ""
    ttopic_listen = f", topic_id=<code>{rec_listen['topic_id']}</code>" if rec_listen["topic_id"] is not None else ""

    await _reply_ok(
        update,
        "✅ Привязки сохранены:\n"
        f"• уведомления: group=<code>{escape(group_key)}</code>, kind=<code>{escape(kind)}</code>, "
        f"chat_id=<code>{rec_main['chat_id']}</code>{ttopic_main}\n"
        f"• слушать ключевые слова: kind=<code>listen</code>, chat_id=<code>{rec_listen['chat_id']}</code>{ttopic_listen}"
    )


async def admin_notif_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_notif_show [group_key] [kind]
    Если group_key не указан — покажем подсказку.
    """
    args = context.args or []
    if not args:
        await _reply_err(update, "ожидаю: /admin_notif_show <group_key> [kind]")
        return

    group_key = args[0].strip()
    kind = (args[1].strip().lower() if len(args) >= 2 else "general")

    rec = get_target(group_key, kind=kind)
    if not rec:
        await _reply_ok(update, f"ℹ️ Привязка для <code>{escape(group_key)}</code> kind=<code>{escape(kind)}</code> не найдена.")
        return

    ttopic = f"\n• topic_id: <code>{rec['topic_id']}</code>" if rec["topic_id"] is not None else ""
    await _reply_ok(update,
        f"<b>Привязка</b>\n"
        f"• group_key: <code>{escape(group_key)}</code>\n"
        f"• kind: <code>{escape(kind)}</code>\n"
        f"• chat_id: <code>{rec['chat_id']}</code>{ttopic}"
    )


async def admin_notif_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_notif_list [kind]
    """
    kind = (context.args[0].strip().lower() if context.args else None)
    rows = list_targets(kind=kind)
    if not rows:
        await _reply_ok(update, "Список пуст.")
        return

    lines = ["<b>Привязки уведомлений</b>"]
    for r in rows:
        ttopic = f", topic_id=<code>{r['topic_id']}</code>" if r["topic_id"] is not None else ""
        lines.append(
            f"• <code>{escape(r['group_key'])}</code> "
            f"(kind=<code>{escape(r['kind'])}</code>): "
            f"chat_id=<code>{r['chat_id']}</code>{ttopic}"
        )
    await _reply_ok(update, "\n".join(lines))


async def admin_notif_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_notif_clear <group_key> [kind]
    """
    args = context.args or []
    if not args:
        await _reply_err(update, "ожидаю: /admin_notif_clear <group_key> [kind]")
        return

    group_key = args[0].strip()
    kind = (args[1].strip().lower() if len(args) >= 2 else "general")

    ok = clear_target(group_key, kind=kind)
    if ok:
        await _reply_ok(update, f"🗑 Привязка удалена: <code>{escape(group_key)}</code> kind=<code>{escape(kind)}</code>.")
    else:
        await _reply_ok(update, f"ℹ️ Нечего удалять: <code>{escape(group_key)}</code> kind=<code>{escape(kind)}</code>.")


async def admin_notif_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_notif_ping <group_key> [kind] [текст...]
    Отправляет тестовое сообщение в привязанный чат/топик.
    """
    args = context.args or []
    if not args:
        await _reply_err(update, "ожидаю: /admin_notif_ping <group_key> [kind] [текст]")
        return

    group_key = args[0].strip()
    kind = (args[1].strip().lower() if len(args) >= 2 and not args[1].lstrip("-").isdigit() else "general")
    text_begin_idx = 2 if kind != "general" or (len(args) >= 2 and not args[1].lstrip("-").isdigit()) else 1
    test_text = " ".join(args[text_begin_idx:]).strip() or "Тест уведомлений ✅"

    rec = resolve_target(group_key, kind=kind, fallback_to_general=True)
    if not rec:
        await _reply_err(update,
            f"нет привязки для <code>{escape(group_key)}</code> "
            f"(kind=<code>{escape(kind)}</code>, fallback=general).")
        return

    await _send_to_target(context, rec["chat_id"], rec["topic_id"], f"🔔 <b>{escape(group_key)}</b> ({escape(kind)}): {escape(test_text)}")
    await _reply_ok(update, f"📤 Отправлено в chat_id=<code>{rec['chat_id']}</code>"
                            f"{' topic_id=<code>'+str(rec['topic_id'])+'</code>' if rec['topic_id'] is not None else ''}.")


# ==== public utility for other handlers =======================================

async def notify_group(context: ContextTypes.DEFAULT_TYPE,
                       group_key: str,
                       text_html: str,
                       kind: str = "general") -> bool:
    """
    Универсальная отправка по привязке.
    Возвращает True/False по факту отправки.
    """
    try:
        rec = resolve_target(group_key, kind=kind, fallback_to_general=True)
        if not rec:
            logger.warning("No notif target for group=%s kind=%s", group_key, kind)
            return False
        await _send_to_target(context, rec["chat_id"], rec["topic_id"], text_html)
        return True
    except Exception:
        logger.exception("notify_group failed")
        return False



