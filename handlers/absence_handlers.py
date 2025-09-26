# -*- coding: utf-8 -*-
import logging
from datetime import date, datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from database.absence_repository import (
    create_absence, update_absence, soft_delete_absence, list_absences,
    list_absences_period,   # <— НОВОЕ
)
from database.repository import UserRepository, USER_ROLE_ADMIN

# --- local date parsers (compat) ---
from datetime import datetime, date


def _parse_date_any(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date: {s}")

def _parse_dates(parts):
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
    ur = UserRepository()
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
    emoji = "🏖" if r["absence_type"] == "vacation" else "🤒"
    return f"{emoji} #{r['id']}: {r['date_from']}—{r['date_to']}" + (f" — {r['comment']}" if r.get("comment") else "")

# --- user: vacation ---
async def vacation_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


# ===== ХЕЛПЕРЫ ДЛЯ АДМИН-ОТЧЁТОВ =====

def _parse_period(args):
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
    ur = UserRepository()
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
    up = _fetch_user_public(uid)
    name = f"{up['first_name']} {up['last_name']}".strip()
    handle = f" 🔗 @{up['username']}" if up['username'] else ""
    left = name if name else f"user_id={uid}"
    return "👤 " + left + handle

# --- admin: list all vacations by period ---
async def vacations_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    d_from, d_to = _parse_period(context.args or [])
    rows = list_absences(user_id=None, absence_type="vacation", from_date=d_from, to_date=d_to)
    if not rows:
        await update.message.reply_text(f"Отпусков не найдено в период {d_from:%Y-%m-%d}..{d_to:%Y-%m-%d}.")
        return
    head = f"🏖 <b>Отпуска</b> ({d_from:%Y-%m-%d}..{d_to:%Y-%m-%d})"
    lines = [head]
    for r in rows:
        uid = int(r["user_id"])
        user_line = _fmt_user_line_by_uid(uid)
        note = (r.get("comment") or "").strip()
        note_part = f" — <i>{note}</i>" if note and note.lower() not in {"отпуск"} else ""
        lines.append(
            f"• {r['date_from']:%Y-%m-%d}…{r['date_to']:%Y-%m-%d} — 🆔 {uid}\n"
            f"{user_line} — отпуск{note_part}"
        )
    await _send_chunked(update, lines, parse_mode="HTML")

# --- admin: list all sick leaves by period ---

async def vacation_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    rows = list_absences(user_id=user.id, absence_type="vacation")
    if not rows:
        await update.message.reply_text("Пока нет записей об отпуске.")
        return
    await update.message.reply_text("Ваши отпуска:\n" + "\n".join(_format_absence_row(r) for r in rows[:50]))

async def vacation_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    user = update.effective_user
    rows = list_absences(user_id=user.id, absence_type="sick")
    if not rows:
        await update.message.reply_text("Пока нет записей о больничном.")
        return
    await update.message.reply_text("Ваши больничные:\n" + "\n".join(_format_absence_row(r) for r in rows[:50]))

async def sick_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# -------- НОВОЕ: отчёты по всем сотрудникам --------

# --- admin: list all vacations by period ---
async def vacations_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return

    d_from, d_to = _parse_period(context.args or [])
    rows = list_absences(user_id=None, absence_type="vacation", from_date=d_from, to_date=d_to)
    if not rows:
        await update.message.reply_text(f"Отпусков не найдено в период {d_from:%Y-%m-%d}..{d_to:%Y-%m-%d}.")
        return

    head = f"🏖 <b>Отпуска</b> ({d_from:%Y-%m-%d}..{d_to:%Y-%m-%d})"
    lines = [head]
    for r in rows:
        uid = int(r["user_id"])
        user_line = _fmt_user_line_by_uid(uid)
        note = (r.get("comment") or "").strip()
        # не дублируем слово "отпуск", если оно совпадает с комментарием
        note_part = f" — <i>{note}</i>" if note and note.lower() not in {"отпуск"} else ""
        item = (
            f"• {r['date_from']:%Y-%m-%d}…{r['date_to']:%Y-%m-%d} — 🆔 {uid}\n"
            f"{user_line} — отпуск{note_part}"
        )
        lines.append(item)

    await _send_chunked(update, lines, parse_mode="HTML")


# --- admin: list all sick leaves by period ---
async def sick_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    d_from, d_to = _parse_period(context.args or [])
    rows = list_absences(user_id=None, absence_type="sick", from_date=d_from, to_date=d_to)
    if not rows:
        await update.message.reply_text(f"Больничных не найдено в период {d_from:%Y-%m-%d}..{d_to:%Y-%m-%d}.")
        return
    head = f"🤒 <b>Больничные</b> ({d_from:%Y-%m-%d}..{d_to:%Y-%m-%d})"
    lines = [head]
    for r in rows:
        uid = int(r["user_id"])
        user_line = _fmt_user_line_by_uid(uid)
        note = (r.get("comment") or "").strip()
        note_part = f" — <i>{note}</i>" if note and note.lower() not in {"больничный"} else ""
        lines.append(
            f"• {r['date_from']:%Y-%m-%d}…{r['date_to']:%Y-%m-%d} — 🆔 {uid}\n"
            f"{user_line} — больничный{note_part}"
        )
    await _send_chunked(update, lines, parse_mode="HTML")

# --- admin: vacations aggregated ---
async def vacations_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not _is_admin(caller.id):
        await update.message.reply_text("⛔ Только для админов.")
        return

    # Диапазон: по умолчанию текущий месяц; можно передать 2 даты: YYYY-MM-DD YYYY-MM-DD
    today = date.today()
    if context.args and len(context.args) >= 2:
        try:
            d_from, d_to = _parse_dates(context.args[:2])
        except Exception:
            await update.message.reply_text("❌ Формат: /vacations_all [YYYY-MM-DD YYYY-MM-DD]")
            return
    else:
        first = today.replace(day=1)
        # последний день месяца: 1-е след. месяца минус день
        if first.month == 12:
            next_month_first = first.replace(year=first.year + 1, month=1)
        else:
            next_month_first = first.replace(month=first.month + 1)
        d_from, d_to = first, next_month_first - timedelta(days=1)

    rows = list_absences_with_users(
        absence_type="vacation",
        from_date=d_from,
        to_date=d_to,
        only_active=True,
    )
    if not rows:
        await update.message.reply_text(f"🏖 Отпуска ({d_from}..{d_to})\n— Нет записей.")
        return

    lines = [f"🏖 Отпуска ({d_from}..{d_to})"]
    for r in rows:
        uname = f"@{r['username']}" if r.get("username") else "—"
        fio = " ".join(filter(None, [r.get("first_name"), r.get("last_name")])).strip()
        if not fio:
            fio = f"user_id={r['user_id']}"
        comment_part = f" — {r['comment']}" if r.get("comment") else ""
        lines.append(
            f"• {r['date_from']}…{r['date_to']} — 🆔 {r['user_id']}\n"
            f"👤 {fio} 🔗 {uname} — отпуск{comment_part}"
        )

    await update.message.reply_text("\n".join(lines[:1200]))  # простая защита от очень длинных сообщений
from database.absence_repository import list_absences_with_users
