# /home/telegrambot/shift_tracker_bot/handlers/duty_handlers.py
# -*- coding: utf-8 -*-
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database.duty_repository import (
    list_duties, create_duty, update_duty, delete_duty,
    auto_assign_for_date, get_assignments
)
from database.repository import UserRepository, USER_ROLE_ADMIN
from html import escape

logger = logging.getLogger(__name__)

# Интерфейс везде цифрами, в БД строки
ROLE_BY_NUM = {1: "leader", 2: "specialist", 3: "junior"}
NUM_BY_ROLE = {"leader": 1, "specialist": 2, "junior": 3}

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

def _parse_ondate(args) -> date:
    if not args:
        return date.today()
    s = " ".join(args).strip().lower()
    if s in ("today", "сегодня"):
        return date.today()
    if s in ("tomorrow", "завтра"):
        return date.today() + timedelta(days=1)
    # DD.MM[.YYYY]
    try:
        parts = s.split(".")
        if len(parts) >= 2:
            d = int(parts[0]); m = int(parts[1])
            y = int(parts[2]) if len(parts) >= 3 else date.today().year
            return date(y, m, d)
    except Exception:
        pass
    # YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return date.today()

def _fmt_assign_row(r) -> str:
    return f"• {escape(r['group_key'])}: <b>{escape(r['title'])}</b> → {r['user_id']}"

# ===== Admin: CRUD duties =====

async def duty_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duty_add <kind_num> <title> |desc| [min_rank]
    kind_num: 1=лидер, 2=специалист, 3=младший специалист
    пример: /duty_add 3 "Обработка инцидентов" |описание| 3
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Формат: /duty_add <1|2|3> <title> [|description|] [min_rank]")
        return

    # kind_num
    if not args[0].isdigit() or int(args[0]) not in ROLE_BY_NUM:
        await update.message.reply_text("Первый аргумент — тип обязанности: 1=лидер, 2=специалист, 3=младший специалист.")
        return
    kind = ROLE_BY_NUM[int(args[0])]

    rest = " ".join(args[1:])
    desc = None
    # По умолчанию min_rank = NUM_BY_ROLE[kind]
    min_rank = NUM_BY_ROLE.get(kind, 2)

    if "|" in rest:
        title, tail = rest.split("|", 1)
        title = title.strip().strip("«»\"'")
        if "|" in tail:
            desc, tail2 = tail.split("|", 1)
            desc = desc.strip()
            tail2 = tail2.strip()
            if tail2.isdigit():
                min_rank = int(tail2)
        else:
            desc = tail.strip()
    else:
        title = rest.strip().strip("«»\"'")

    new_id = create_duty(title=title, kind=kind, description=desc, min_rank=min_rank)
    await update.message.reply_text(f"✅ Duty создан: id={new_id}" if new_id else "❌ Не удалось создать.")

async def duties_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duties_list [1|2|3]
    1=лидер, 2=специалист, 3=младший специалист
    """
    args = context.args or []
    kind = None
    if args:
        if args[0].isdigit() and int(args[0]) in ROLE_BY_NUM:
            kind = ROLE_BY_NUM[int(args[0])]
        else:
            await update.message.reply_text("Фильтр: 1=лидер, 2=специалист, 3=младший специалист")
            return

    rows = list_duties(kind=kind)
    if not rows:
        await update.message.reply_text("Пока нет обязанностей.")
        return
    lines = []
    for r in rows:
        kind_num = NUM_BY_ROLE.get(r['kind'], r['kind'])
        lines.append(f"#{r['id']} [{kind_num}] <b>{escape(r['title'])}</b> (min_rank={r['min_rank']})")
        if r.get("description"):
            lines.append(f"  — {escape(r['description'])}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def duty_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duty_update <id> field=value [field=value ...]
    fields: title,description,kind,min_rank,is_active
    kind: 1|2|3 (1=leader, 2=specialist, 3=junior)
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 2 or not args[0].isdigit():
        await update.message.reply_text("Формат: /duty_update <id> field=value ...")
        return
    duty_id = int(args[0])
    updates = {}
    for pair in args[1:]:
        if "=" in pair:
            k, v = pair.split("=", 1)
            k = k.strip(); v = v.strip()
            if k == "kind":
                # принимаем 1/2/3 и переводим в строку для БД
                if v.isdigit() and int(v) in ROLE_BY_NUM:
                    updates[k] = ROLE_BY_NUM[int(v)]
                else:
                    await update.message.reply_text("kind должен быть 1 (leader), 2 (specialist) или 3 (junior).")
                    return
            elif k in ("min_rank",):
                if v.isdigit():
                    updates[k] = int(v)
            elif k in ("is_active",):
                updates[k] = (v.lower() in ("1","true","yes","y","on"))
            else:
                updates[k] = v
    ok = update_duty(duty_id, **updates)
    await update.message.reply_text("✅ Обновлено." if ok else "❌ Не удалось обновить.")

async def duty_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duty_delete <id>
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Формат: /duty_delete <id>")
        return
    ok = delete_duty(int(args[0]))
    await update.message.reply_text("🗑 Удалено." if ok else "❌ Не удалось удалить.")

# ===== Assignments =====

async def assign_duties(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /assign_duties [YYYY-MM-DD] [group_key]
    Если дата не указана — сегодня. Если ключ не указан — все группы.
    """
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("⛔ Только для админов.")
        return

    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        on_date = _parse_date(args[0])
        gkey = args[1] if len(args) > 1 else None
    else:
        on_date = date.today()
        gkey = args[0] if args else None

    count = auto_assign_for_date(on_date, author_id=uid, group_key=gkey)
    await update.message.reply_text(f"✅ Назначено {count} обязанностей на {on_date}.")

async def duties_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /duties_today [YYYY-MM-DD] [group_key]
    """
    args = context.args or []
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        on_date = _parse_date(args[0])
        gkey = args[1] if len(args) > 1 else None
    else:
        on_date = date.today()
        gkey = args[0] if args else None

    rows = get_assignments(on_date, gkey)
    if not rows:
        await update.message.reply_text("Назначений нет.")
        return
    lines = [f"🗓 <b>{on_date.strftime('%Y-%m-%d')}</b>"]
    for r in rows:
        lines.append(f"• <b>{escape(r['group_key'])}</b> — {escape(r['title'])} → {r['user_id']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def my_duties(update: Update, context: ContextTypes.DEFAULT_TYPE):
    on_date = _parse_ondate(context.args)
    uid = update.effective_user.id
    rows = get_assignments(on_date)

    mine = [r for r in rows if int(r["user_id"]) == int(uid)]
    if not mine:
        await update.message.reply_text(f"У вас нет назначенных обязанностей на {on_date:%Y-%m-%d}.")
        return

    lines = [f"🗓 {on_date:%A}, {on_date:%Y-%m-%d}"]
    for r in mine:
        lines.append(f"• {r['title']} — группа {r['group_key']}")
    await update.message.reply_text("\n".join(lines))

# handlers/duty_handlers.py (добавьте рядом)
async def my_duties_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    start = date.today()
    horizon = 30
    for i in range(horizon + 1):
        day = start + timedelta(days=i)
        mine = [r for r in get_assignments(day) if int(r["user_id"]) == int(uid)]
        if mine:
            lines = [f"🗓 {day:%A}, {day:%Y-%m-%d} — ближайшие ваши обязанности:"]
            for r in mine:
                lines.append(f"• {r['title']} — группа {r['group_key']}")
            await update.message.reply_text("\n".join(lines))
            return
    await update.message.reply_text("В ближайшие 30 дней ваших назначений не нашлось.")
