# /home/telegrambot/shift_tracker_bot/handlers/absence_handlers.py
# -*- coding: utf-8 -*-
"""
Модуль обработчиков команд Telegram-бота для управления отпусками и больничными.

Содержит функции для:
- Добавления, редактирования, удаления и просмотра отпусков и больничных
- Административных операций (управление записями всех пользователей)
- Формирования отчетов за период
- Проверки прав доступа пользователей

Все функции работают с базой данных через absence_repository и users_repository
"""

import logging
from datetime import date, datetime, timedelta
import re
from telegram import Update
from telegram.ext import ContextTypes
from html import escape
from handlers.help_texts import HELP_VACATIONS_SHORT
from database.absence_repository import (
    create_absence, update_absence, soft_delete_absence, list_absences,
    list_absences_period, list_absences_with_users,  # <— НОВОЕ
)
import database.users_repository as user_repository
from database.users_repository import USER_ROLE_ADMIN

# --- local date parsers (compat) ---
from database import time_repository as time_repo


def _parse_date_any(s: str) -> date:
    """Парсит дату из строки в нескольких форматах"""
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date: {s}")

def _parse_dates(parts):
    """Парсит две даты из списка строк и возвращает их в правильном порядке"""
    if len(parts) < 2:
        raise ValueError("need 2 dates: start end")
    d1 = _parse_date_any(parts[0])
    d2 = _parse_date_any(parts[1])
    if d2 < d1:
        d1, d2 = d2, d1
    return d1, d2
logger = logging.getLogger(__name__)

def _fmt_user_line(r: dict) -> str:
    """
    Возвращает строку вида:
    '👤 Имя Фамилия 🔗 @username'
    Фолбэк, если нет имени: '👤 user_id=123'
    """
    fn = (r.get("first_name") or "").strip()
    ln = (r.get("last_name") or "").strip()
    un = (r.get("tg_username") or "").strip()
    uid = r.get("user_id")

    parts = []
    name = f"{fn} {ln}".strip()
    if name:
        parts.append(name)
    else:
        parts.append(f"user_id={uid}")
    if un:
        parts.append(f"🔗 @{un}")
    return "👤 " + " ".join(parts)


def _is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    ur = user_repository
    # Надёжная проверка по БД (без чувствительности к регистру)
    if hasattr(ur, "is_user_admin"):
        try:
            return bool(ur.is_user_admin(user_id))
        except Exception:
            pass

    # Fallback: если где-то всё ещё используют get_user_roles/константу
    roles = []
    if hasattr(ur, "get_user_roles"):
        try:
            roles = ur.get_user_roles(user_id) or []
        except Exception:
            roles = []
    roles_lower = {str(r).strip().lower() for r in roles}
    return ("admin" in roles_lower)


# ---- НОВОЕ: парсинг периода для общих отчётов ----

def _format_absence_row(r):
    """Форматирует одну запись об отсутствии для вывода"""
    emoji = "🏖" if r["absence_type"] == "vacation" else "🤒"
    return f"{emoji} #{r['id']}: {r['date_from']}—{r['date_to']}" + (f" — {r['comment']}" if r.get("comment") else "")

# --- user: vacation ---
async def vacation_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление отпуска пользователем"""
    user = update.effective_user
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Формат: /vacation_add YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        d1, d2 = _parse_dates(args[:2])
        comment = " ".join(args[2:]) if len(args) > 2 else None
        new_id = create_absence(user.id, "vacation", d1, d2, comment, author_id=user.id)
        await update.message.reply_text(
            f"✅ Отпуск создан: #{new_id} {d1}—{d2}" if new_id else "❌ Не удалось создать запись."
        )
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("❌ Ошибка парсинга даты. Формат YYYY-MM-DD.")

# ---- НОВОЕ: формат имени в отчётах ----
def _fmt_user(r: dict) -> str:
    """Форматирует информацию о пользователе для отчётов"""
    fn = (r.get("first_name") or "").strip()
    ln = (r.get("last_name") or "").strip()
    un = (r.get("tg_username") or "").strip()
    uid = int(r.get("user_id"))
    name = f"{fn} {ln}".strip()
    if name and un:
        return f"{name} (@{un})"
    if name:
        return name
    if un:
        return f"@{un}"
    return f"user_id={uid}"

# ---- НОВОЕ: безопасная отправка длинных списков ----

async def help_vacations_short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Короткая справка по отпускам."""
    await update.message.reply_text(HELP_VACATIONS_SHORT, parse_mode="HTML")


# ===== ХЕЛПЕРЫ ДЛЯ АДМИН-ОТЧЁТОВ =====

def _parse_period(args):
    """Парсит период из аргументов команды"""
    today = date.today()
    if len(args) >= 2:
        d1 = datetime.strptime(args[0], "%Y-%m-%d").date()
        d2 = datetime.strptime(args[1], "%Y-%m-%d").date()
        if d1 > d2:
            d1, d2 = d2, d1
        return d1, d2
    first = today.replace(day=1)
    next_month = (date(first.year + 1, 1, 1) if first.month == 12
                  else date(first.year, first.month + 1, 1))
    last = next_month - timedelta(days=1)
    return first, last

async def _send_chunked(update: Update, lines: list[str], parse_mode: str | None = None):
    """Отправляет длинные сообщения частями для обхода ограничения длины Telegram"""
    buf = ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > 3500:
            await update.message.reply_text(buf, parse_mode=parse_mode)
            buf = ln
        else:
            buf = (buf + "\n" + ln) if buf else ln
    if buf:
        await update.message.reply_text(buf, parse_mode=parse_mode)

def _fetch_user_public(uid: int) -> dict:
    """Получает публичную информацию о пользователе из базы данных"""
    ur = user_repository
    user_obj = None
    for meth in ("get_user_by_id", "get_user", "load_user", "get_user_profile", "find_by_id", "get"):
        if hasattr(ur, meth):
            try:
                user_obj = getattr(ur, meth)(uid)
                if user_obj:
                    break
            except Exception:
                user_obj = None
    u = user_obj or {}
    def _pick(*keys):
        for k in keys:
            v = u.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() != "none":
                return s
        return ""
    return {
        "first_name": _pick("first_name", "firstname", "firstName"),
        "last_name":  _pick("last_name", "lastname", "lastName"),
        "username":   _pick("username", "tg_username", "user_name", "login"),
    }

def _fmt_user_line_by_uid(uid: int) -> str:
    """Форматирует строку с информацией о пользователе по его ID"""
    up = _fetch_user_public(uid)
    name = f"{up['first_name']} {up['last_name']}".strip()
    handle = f" 🔗 @{up['username']}" if up['username'] else ""
    left = name if name else f"user_id={uid}"
    return "👤 " + left + handle


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
def _parse_vacations_all_args(args: list[str]) -> tuple[date, date, dict]:
    """
    Разбор аргументов /vacations_all.
    Возвращает (d_from, d_to, filters) где filters может содержать:
      - 'user_id': int
      - 'username': str (без @)
      - 'user_ids': list[int] (для тайм-группы)
    Правила:
      * Если переданы две даты в начале — используем как период.
      * Далее допускается один из фильтров: @username | <user_id> | <group_key>.
      * Если даты не указаны — берём весь текущий год.
    """
    today = date.today()
    d_from = date(today.year, 1, 1)
    d_to   = date(today.year, 12, 31)
    filters: dict = {}

    tokens = list(args or [])
    # Период (две даты первым и вторым токеном)
    if len(tokens) >= 2 and _DATE_RE.match(tokens[0]) and _DATE_RE.match(tokens[1]):
        d_from = datetime.strptime(tokens[0], "%Y-%m-%d").date()
        d_to   = datetime.strptime(tokens[1], "%Y-%m-%d").date()
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        tokens = tokens[2:]

    if tokens:
        t = tokens[0].strip()
        if t.startswith("@"):
            filters["username"] = t.lstrip("@")
        elif t.isdigit():
            filters["user_id"] = int(t)
        else:
            # считаем это ключом тайм-группы
            gi = time_repo.get_group_info(t)
            if gi:
                filters["user_ids"] = [int(m["user_id"]) for m in (gi.get("members") or []) if m.get("user_id")]
    return d_from, d_to, filters

# --- admin: list all vacations by period (HTML + joined users, no t.me preview) ---
async def vacations_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все отпуска за период с HTML-разметкой.
       Формат:
       🏖 <b>Отпуска</b> (YYYY-MM-DD..YYYY-MM-DD)
       • YYYY-MM-DD…YYYY-MM-DD — 🆔 <b>ID</b>
       👤 Имя Фамилия 🔗 @username — <b>отпуск</b> — <i>комментарий</i>
    """
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return

    # Поддержка периода и фильтров: /vacations_all [YYYY-MM-DD YYYY-MM-DD] [@username|user_id|group_key]
    d_from, d_to, filters = _parse_vacations_all_args(context.args or [])

    rows = list_absences_with_users(
        absence_type="vacation",
        from_date=d_from,
        to_date=d_to,
        only_active=True,
    )

    # Применяем фильтры по пользователю/группе при необходимости
    if rows and filters:
        if "user_id" in filters:
            uid_target = int(filters["user_id"])
            rows = [r for r in rows if int(r.get("user_id", 0)) == uid_target]
        elif "username" in filters:
            u_target = str(filters["username"]).lstrip("@").lower()
            rows = [r for r in rows if str(r.get("username", "")).lstrip("@").lower() == u_target]
        elif "user_ids" in filters:
            uid_set = {int(x) for x in filters["user_ids"]}
            rows = [r for r in rows if int(r.get("user_id", 0)) in uid_set]

    if not rows:
        await update.message.reply_text(
            f"🏖 <b>Отпуска</b> ({d_from:%Y-%m-%d}..{d_to:%Y-%m-%d})\n— Нет записей.",
            parse_mode="HTML",
        )
        return

    lines = [f"🏖 <b>Отпуска</b> ({d_from:%Y-%m-%d}..{d_to:%Y-%m-%d})"]

    for r in rows:
        absence_id = int(r["id"])
        uid = int(r["user_id"])

        first_name = (r.get("first_name") or "").strip()
        last_name  = (r.get("last_name") or "").strip()
        username   = (r.get("username") or "").strip().lstrip("@")

        fio = " ".join(x for x in [first_name, last_name] if x).strip()
        left = escape(fio, quote=False) if fio else f"user_id=<code>{uid}</code>"

        if username:
            uname_html = f"@{escape(username, quote=False)}"  # текстом, без ссылки
            user_line = f"👤 {left} 🔗 {uname_html}"
        else:
            user_line = f"👤 {left}"

        note = (r.get("comment") or "").strip()
        note_part = f" — <i>{escape(note, quote=False)}</i>" if note and note.lower() != "отпуск" else ""

        lines.append(f"• {r['date_from']:%Y-%m-%d}…{r['date_to']:%Y-%m-%d} — 🆔 <code>{absence_id}</code>")
        lines.append(f"{user_line} — <b>отпуск</b>{note_part}")

    await _send_chunked(update, lines, parse_mode="HTML")
    await help_vacations_short_command(update, context)


# --- admin: list all sick leaves by period ---

async def vacation_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает отпуска текущего пользователя"""
    user = update.effective_user
    rows = list_absences(user_id=user.id, absence_type="vacation")
    if not rows:
        await update.message.reply_text("Пока нет записей об отпуске.")
        await help_vacations_short_command(update, context)
        return
    await update.message.reply_text("Ваши отпуска:\n" + "\n".join(_format_absence_row(r) for r in rows[:50]))
    await help_vacations_short_command(update, context)

async def vacation_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование отпуска пользователем"""
    user = update.effective_user
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /vacation_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        absence_id = int(args[0])
        d1, d2 = _parse_dates(args[1:3])
        comment = " ".join(args[3:]) if len(args) > 3 else None
        ok = update_absence(absence_id, user_id=user.id, date_from=d1, date_to=d2, comment=comment, editor_id=user.id, is_admin=False)
        await update.message.reply_text("✅ Обновлено." if ok else "❌ Не удалось обновить (проверьте id/права).")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /vacation_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")

async def vacation_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление отпуска пользователем"""
    user = update.effective_user
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Формат: /vacation_del <id>")
        return
    try:
        absence_id = int(args[0])
        ok = soft_delete_absence(absence_id, user_id=user.id, is_admin=False)
        await update.message.reply_text("🗑 Удалено." if ok else "❌ Не удалось удалить (проверьте id).")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /vacation_del <id>")

# --- user: sick ---
async def sick_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление больничного пользователем"""
    user = update.effective_user
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Формат: /sick_add YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        d1, d2 = _parse_dates(args[:2])
        comment = " ".join(args[2:]) if len(args) > 2 else None
        new_id = create_absence(user.id, "sick", d1, d2, comment, author_id=user.id)
        await update.message.reply_text(f"✅ Больничный создан: #{new_id} {d1}—{d2}" if new_id else "❌ Не удалось создать.")
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("❌ Ошибка парсинга даты. Формат YYYY-MM-DD.")

async def sick_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает больничные текущего пользователя"""
    user = update.effective_user
    rows = list_absences(user_id=user.id, absence_type="sick")
    if not rows:
        await update.message.reply_text("Пока нет записей о больничном.")
        return
    await update.message.reply_text("Ваши больничные:\n" + "\n".join(_format_absence_row(r) for r in rows[:50]))

async def sick_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование больничного пользователем"""
    user = update.effective_user
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /sick_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        absence_id = int(args[0])
        d1, d2 = _parse_dates(args[1:3])
        comment = " ".join(args[3:]) if len(args) > 3 else None
        ok = update_absence(absence_id, user_id=user.id, date_from=d1, date_to=d2, comment=comment, editor_id=user.id, is_admin=False)
        await update.message.reply_text("✅ Обновлено." if ok else "❌ Не удалось обновить (проверьте id/права).")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /sick_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")

async def sick_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление больничного пользователем"""
    user = update.effective_user
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Формат: /sick_del <id>")
        return
    try:
        absence_id = int(args[0])
        ok = soft_delete_absence(absence_id, user_id=user.id, is_admin=False)
        await update.message.reply_text("🗑 Удалено." if ok else "❌ Не удалось удалить (проверьте id).")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /sick_del <id>")

# --- admin: vacation ---
async def admin_vacation_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление отпуска администратором для любого пользователя"""
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /admin_vacation_add <user_id> YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        target_id = int(args[0])
        d1, d2 = _parse_dates(args[1:3])
        comment = " ".join(args[3:]) if len(args) > 3 else None
        new_id = create_absence(target_id, "vacation", d1, d2, comment, author_id=caller.id)
        await update.message.reply_text(f"✅ Создано: #{new_id}" if new_id else "❌ Не удалось создать.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}\nФормат: /admin_vacation_add <user_id> YYYY-MM-DD YYYY-MM-DD [комментарий]")

async def admin_vacation_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование отпуска администратором"""
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /admin_vacation_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        absence_id = int(args[0])
        d1, d2 = _parse_dates(args[1:3])
        comment = " ".join(args[3:]) if len(args) > 3 else None
        ok = update_absence(absence_id, user_id=0, date_from=d1, date_to=d2, comment=comment, editor_id=caller.id, is_admin=True)
        await update.message.reply_text("✅ Обновлено." if ok else "❌ Не удалось обновить.")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /admin_vacation_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")

async def admin_vacation_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление отпуска администратором"""
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Формат: /admin_vacation_del <id>")
        return
    try:
        absence_id = int(args[0])
        ok = soft_delete_absence(absence_id, user_id=0, is_admin=True)
        await update.message.reply_text("🗑 Удалено." if ok else "❌ Не удалось удалить.")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /admin_vacation_del <id>")

# --- admin: sick ---
async def admin_sick_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление больничного администратором для любого пользователя"""
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /admin_sick_add <user_id> YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        target_id = int(args[0])
        d1, d2 = _parse_dates(args[1:3])
        comment = " ".join(args[3:]) if len(args) > 3 else None
        new_id = create_absence(target_id, "sick", d1, d2, comment, author_id=caller.id)
        await update.message.reply_text(f"✅ Создано: #{new_id}" if new_id else "❌ Не удалось создать.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}\nФормат: /admin_sick_add <user_id> YYYY-MM-DD YYYY-MM-DD [комментарий]")

async def admin_sick_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование больничного администратором"""
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /admin_sick_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")
        return
    try:
        absence_id = int(args[0])
        d1, d2 = _parse_dates(args[1:3])
        comment = " ".join(args[3:]) if len(args) > 3 else None
        ok = update_absence(absence_id, user_id=0, date_from=d1, date_to=d2, comment=comment, editor_id=caller.id, is_admin=True)
        await update.message.reply_text("✅ Обновлено." if ok else "❌ Не удалось обновить.")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /admin_sick_edit <id> YYYY-MM-DD YYYY-MM-DD [комментарий]")

async def admin_sick_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление больничного администратором"""
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Формат: /admin_sick_del <id>")
        return
    try:
        absence_id = int(args[0])
        ok = soft_delete_absence(absence_id, user_id=0, is_admin=True)
        await update.message.reply_text("🗑 Удалено." if ok else "❌ Не удалось удалить.")
    except Exception:
        await update.message.reply_text("❌ Ошибка. Формат: /admin_sick_del <id>")

async def sick_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Больничные за период с HTML-разметкой и ФИО/username из БД.
       Формат:
       🤒 <b>Больничные</b> (YYYY-MM-DD..YYYY-MM-DD)
       • YYYY-MM-DD…YYYY-MM-DD — 🆔 <b>ID</b>
       👤 Имя Фамилия 🔗 <a href="https://t.me/username">@username</a> — <b>больничный</b> — <i>комментарий</i>
    """
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return

    d_from, d_to = _parse_period(context.args or [])

    rows = list_absences_with_users(
        absence_type="sick",
        from_date=d_from,
        to_date=d_to,
        only_active=True,
    )

    if not rows:
        await update.message.reply_text(
            f"🤒 <b>Больничные</b> ({d_from:%Y-%m-%d}..{d_to:%Y-%m-%d})\n— Нет записей.",
            parse_mode="HTML",
        )
        return

    lines = [f"🤒 <b>Больничные</b> ({d_from:%Y-%m-%d}..{d_to:%Y-%m-%d})"]

    for r in rows:
        absence_id = int(r["id"])
        uid = int(r["user_id"])

        # ФИО / username из join-а
        first_name = (r.get("first_name") or "").strip()
        last_name  = (r.get("last_name") or "").strip()
        username   = (r.get("username") or "").strip().lstrip("@")

        fio = " ".join(x for x in [first_name, last_name] if x).strip()
        left = escape(fio, quote=False) if fio else f"user_id=<code>{uid}</code>"

        if username:
            uname_html = f"@{escape(username, quote=False)}"
            user_line = f"👤 {left} 🔗 {uname_html}"
        else:
            user_line = f"👤 {left}"

        note = (r.get("comment") or "").strip()
        note_part = f" — <i>{escape(note, quote=False)}</i>" if note and note.lower() != "больничный" else ""

        lines.append(f"• {r['date_from']:%Y-%m-%d}…{r['date_to']:%Y-%m-%d} — 🆔 <code>{absence_id}</code>")
        lines.append(f"{user_line} — <b>больничный</b>{note_part}")

    await _send_chunked(update, lines, parse_mode="HTML")

