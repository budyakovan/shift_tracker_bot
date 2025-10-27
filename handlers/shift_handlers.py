# /home/telegrambot/shift_tracker_bot/handlers/shift_handlers.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any

from telegram import Update, User
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import shift_repository as shift_repo

logger = logging.getLogger(__name__)

DEFAULT_TZ = "Europe/Moscow"


def _fmt_user(u: Dict[str, Any]) -> str:
    uid = u.get("user_id")
    fn = (u.get("first_name") or "").strip()
    ln = (u.get("last_name") or "").strip()
    un = (u.get("username") or "").strip()
    name = (fn + " " + ln).strip() or (("@" + un) if un else str(uid))
    link = f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'
    if un:
        return f"👤 {link}  <code>@{html.escape(un)}</code>"
    return f"👤 {link}"


def _fmt_usercard(u) -> str:
    nick = f"@{u.username}" if u.username else ""
    name = u.display_name
    return f"• {name} {nick}".strip()


async def on_shift_now(update: Update, context: CallbackContext) -> None:
    args = context.args or []
    group_key = " ".join(args).strip() or None

    res = get_on_shift_now(
        now=datetime.utcnow(),
        tz_name="Europe/Moscow",
        group_key=group_key,
        return_debug=False,
    )
    if not res:
        await update.message.reply_text("🕒 Сейчас: никто не на смене.")
        return

    lines = "\n".join(_fmt_usercard(u) for u in res)
    if group_key:
        await update.message.reply_text(f"🕒 На смене (группа: *{group_key}*):\n{lines}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"🕒 На смене:\n{lines}")


async def on_shift_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /on_shift_debug [group_key] [--tz=...] [--office] [--include-afk]
    """
    args = context.args or []
    group_key: Optional[str] = None
    tz_name = DEFAULT_TZ
    office_only = False
    include_afk = False

    for a in list(args):
        la = a.lower()
        if la.startswith("--tz="):
            tz_name = a.split("=", 1)[1].strip() or DEFAULT_TZ
            args.remove(a)
        elif la == "--office":
            office_only = True
            args.remove(a)
        elif la in ("--include-afk", "--afk"):
            include_afk = True
            args.remove(a)

    if args:
        group_key = args[0]

    dbg = shift_repo.get_on_shift_now_debug(
        tz_name=tz_name,
        group_key=group_key,
        include_afk=include_afk,
        office_only=office_only,
    )

    on = dbg.get("on_shift", []) or []
    skipped = dbg.get("skipped", []) or []
    header = f"🧪 Debug — now={html.escape(dbg.get('now',''))}, tz={tz_name}"
    if group_key:
        header += f", group={html.escape(group_key)}"

    lines = [header, ""]
    lines.append(f"✅ На смене ({len(on)}):")
    if on:
        lines += ["  • " + html.escape((u.get('first_name') or '') + " " + (u.get('last_name') or '')).strip()
                  + (f" (@{html.escape(u.get('username') or '')})" if u.get('username') else "")
                  + f" [id={u.get('user_id')}]"
                  for u in on]
    else:
        lines.append("  —")

    lines.append("")
    lines.append(f"⛔ Исключены ({len(skipped)}):")
    if skipped:
        for s in skipped:
            uid = s.get("user_id")
            reasons = ", ".join(s.get("reasons", []))
            lines.append(f"  • id={uid}: {reasons}")
    else:
        lines.append("  —")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def is_on_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /is_on_shift [@username|id] [group_key] [--tz=...] [--office] [--include-afk]
    Если пользователь не указан — проверяем автора команды.
    """
    args = context.args or []
    tz_name = DEFAULT_TZ
    office_only = False
    include_afk = False
    group_key: Optional[str] = None
    target_id: Optional[int] = None

    # параметры-флаги
    rest: List[str] = []
    for a in args:
        la = a.lower()
        if la.startswith("--tz="):
            tz_name = a.split("=", 1)[1].strip() or DEFAULT_TZ
        elif la == "--office":
            office_only = True
        elif la in ("--include-afk", "--afk"):
            include_afk = True
        else:
            rest.append(a)

    # цель
    if rest:
        first = rest[0]
        if first.startswith("@"):
            # попробуем найти в чате — но у нас нет списка, поэтому опустим и ожидаем id
            pass
        else:
            try:
                target_id = int(first)
                rest = rest[1:]
            except Exception:
                pass

    if rest:
        group_key = rest[0]

    if target_id is None:
        me: User = update.effective_user
        target_id = me.id

    ok = shift_repo.is_on_shift_now(
        user_id=target_id,
        tz_name=tz_name,
        group_key=group_key,
        include_afk=include_afk,
        office_only=office_only,
    )
    msg = f"id={target_id} — {'✅ на смене' if ok else '⛔ не на смене'} (tz={tz_name})"
    if group_key:
        msg += f", group={html.escape(group_key)}"
    if office_only:
        msg += ", office-only"
    if include_afk:
        msg += ", include-afk"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
