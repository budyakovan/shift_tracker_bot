# -*- coding: utf-8 -*-
"""
Админ-хендлеры пользователей (компактный вывод).
— ID печатаются в <code>…</code> для быстрого копирования,
— «ожидающие» и «зарегистрированные» блоками,
— хвост «Доступные команды» читается из handlers/help.headlers.help.txt (есть fallback),
— совместим с разными именами функций в репозиториях,
— включает алиасы remove_user / update_all_users и простые заглушки legacy-групп, чтобы не падал импорт из main.py.
"""

from __future__ import annotations

import logging
import inspect
from html import escape
from pathlib import Path
from typing import Any, Iterable, Optional, Callable

from telegram import Update
from telegram.ext import ContextTypes

from utils.decorators import require_admin
from database.repository import UserRepository
from handlers.help_texts import HELP_USERS_SHORT
logger = logging.getLogger(__name__)

def _load_admin_users_footer() -> str:
    # Берём короткую шпаргалку из help_texts, без файлов на диске
    return HELP_USERS_SHORT

# --- В _norm_user ДОБАВЬ поле 'status' в возвращаемый словарь
def _norm_user(u: Any) -> dict[str, Any]:
    """Приводим запись пользователя к унифицированному виду."""
    def g(obj, *keys, default=None):
        for k in keys:
            if isinstance(obj, dict):
                if k in obj and obj[k] is not None:
                    return obj[k]
            else:
                if hasattr(obj, k):
                    v = getattr(obj, k)
                    if v is not None:
                        return v
        return default

    uid = g(u, "user_id", "telegram_id", "tg_id", "id")
    fn = (g(u, "first_name", "firstname", "firstName", default="") or "").strip()
    ln = (g(u, "last_name", "lastname", "lastName", default="") or "").strip()
    full = (" ".join([x for x in (fn, ln) if x]) or (g(u, "name", "full_name", default="") or "")).strip()
    username = (g(u, "username", "user_name", "login", default="") or "").lstrip("@")
    status = (g(u, "status", default="") or "").strip().lower()
    is_approved = bool(
        g(u, "is_approved", "approved", default=False)
        or status in {"approved", "active", "ok"}
    )
    role = (g(u, "role", "user_role", default="") or "").strip().lower()
    is_admin = bool(g(u, "is_admin", "admin", default=False) or role in {"admin", "owner", "root"})
    group_key = g(u, "group_key", "group", "group_id", "group_name", default=None)

    return {
        "uid": uid,
        "name": full,
        "username": username,
        "is_approved": is_approved,
        "is_admin": is_admin,
        "group_key": group_key,
        "status": status,
    }


def _try_repo_funcs(module, names: Iterable[str]) -> Optional[Callable[..., Any]]:
    """Вернёт первую существующую функцию из набора имён."""
    for n in names:
        fn = getattr(module, n, None)
        if callable(fn):
            return fn
    return None


def _safe_call(fn: Optional[Callable[..., Any]], *args, **kwargs) -> Any:
    """
    Аккуратно вызываем функции репозитория.
    Больше НЕ подсовываем None вслепую — только если первый небинденый параметр похож на conn/db.
    """
    if fn is None:
        return None
    try:
        return fn(*args, **kwargs)
    except TypeError as e:
        # Попробуем определить, действительно ли нужен "conn"/"db" первым параметром
        try:
            sig = inspect.signature(fn)
            params = list(sig.parameters.values())

            # если метод уже привязан к экземпляру (bound), выкидываем "self"
            if getattr(fn, "__self__", None) is not None and params:
                params = params[1:]

            name0 = params[0].name if params else ""
            if name0 in {"conn", "db", "session", "connection"}:
                return fn(None, *args, **kwargs)
        except Exception:
            pass

        logger.warning("Repo call TypeError: %s", e)
        return None
    except Exception as e:
        logger.warning("Repo call failed: %s", e)
        return None




def _format_user_line(u: dict[str, Any], with_icon: bool = True) -> str:
    icon = "👑" if u.get("is_admin") else "👤"
    uid = u.get("uid")
    name = escape((u.get("name") or "").strip()) or str(uid)
    uname = u.get("username")
    piece = f"<code>{uid}</code> — {name}"
    if uname:
        piece += f" @{escape(uname)}"
    return f"{icon} {piece}" if with_icon else piece


def _get_all_users() -> list[dict[str, Any]]:
    """Достаёт всех пользователей из user_repository (с fallback по именам функций)."""
    try:
        from database import user_repository as user_repo
    except Exception as e:
        logger.error("user_repository import failed: %s", e)
        return []

    getter = _try_repo_funcs(
        user_repo,
        (
            "list_users",
            "list_all_users",
            "get_all_users",
            "all_users",
            "users_all",
            "get_users",
        ),
    )
    raw = _safe_call(getter) or []
    return [_norm_user(x) for x in raw if x is not None]


# --- ЗАМЕНИ целиком _get_pending_users на:
# --- ЗАМЕНИ целиком _get_pending_users на:
def _get_pending_users() -> list[dict[str, Any]]:
    """
    Определяем «ожидающих» только по признаку is_approved=False
    в общем списке пользователей. Не полагаемся на отдельные
    list_pending/pending_* функции, чтобы избежать рассинхрона.
    """
    all_users = _get_all_users()
    return [u for u in all_users if not u.get("is_approved")]

def _call_repo_variants(fn: Callable[..., Any], *base_args) -> Optional[bool]:
    """
    Пробуем несколько сигнатур вызова функции репозитория:
    (user_id), (user_id, True), (None, user_id), (None, user_id, True).
    Возвращаем None если все варианты не сработали, иначе bool-значение результата.
    """
    variants = [
        base_args,
        (*base_args, True),
        (None, *base_args),
        (None, *base_args, True),
    ]
    for args in variants:
        try:
            res = fn(*args)
            # Некоторые функции ничего не возвращают — считаем это успехом
            return True if res is None else bool(res)
        except TypeError:
            continue
        except Exception as e:
            logger.warning("Repo call failed for %s%r: %s", getattr(fn, "__name__", fn), args, e)
            continue
    return None

def _try_signatures(fn: Callable[..., Any], argsets: list[tuple]) -> Optional[bool]:
    """
    Пробуем вызвать fn с разными наборами аргументов.
    Для каждой сигнатуры пробуем ещё вариант с ведущим None (на случай conn/db).
    Возвращаем None, если ничего не подошло; иначе bool результата (None -> True).
    """
    for args in argsets:
        for prefix in ((), (None,)):
            try:
                res = fn(*prefix, *args)
                return True if res is None else bool(res)
            except TypeError:
                continue
            except Exception as e:
                logger.warning("Repo call failed for %s%r: %s", getattr(fn, "__name__", fn), (prefix + args), e)
                continue
    return None


def _approve_user_repo(user_id: int, admin_id: Optional[int] = None) -> bool:
    """
    Пытаемся одобрить пользователя. Репозиторий может ожидать:
      - approve_user(user_id)
      - approve_user(user_id, admin_id)
      - и те же варианты с ведущим conn/None
    """
    try:
        from database import user_repository as user_repo
    except Exception as e:
        logger.error("user_repository import failed: %s", e)
        return False

    names = (
        "approve_user", "approve", "admin_approve",
        "set_approved", "set_is_approved", "mark_approved",
        "accept_user", "activate_user", "set_status",
    )
    argsets: list[tuple] = [(user_id,)]
    if admin_id is not None:
        argsets.insert(0, (user_id, admin_id))  # сначала пробуем с admin_id

    for name in names:
        fn = getattr(user_repo, name, None)
        if callable(fn):
            ok = _try_signatures(fn, argsets)
            if ok is not None:
                return ok
    return False

def _remove_from_pending_repo(user_id: int) -> Optional[bool]:
    """
    Если в репозитории есть явная функция чистки pending — используем её.
    Сигнатура ожидается как (user_id) [+ возможный ведущий None].
    """
    try:
        from database import user_repository as user_repo
    except Exception:
        return None

    names = (
        "remove_from_pending", "delete_pending", "clear_pending",
        "pending_remove", "remove_pending_user", "unset_pending",
    )
    for name in names:
        fn = getattr(user_repo, name, None)
        if callable(fn):
            return _try_signatures(fn, [(user_id,)])
    return None

def _set_group_repo(user_id: int, group_key: str) -> Optional[bool]:
    try:
        from database import group_repository as group_repo
    except Exception:
        return None
    if not group_repo:
        return None

    for name in ("set_user_group", "assign_user_to_group", "set_group"):
        fn = getattr(group_repo, name, None)
        if callable(fn):
            return _try_signatures(fn, [(user_id, group_key)])
    return None


# ============================ handlers =====================================

@require_admin
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список пользователей: сначала ожидающие, затем одобренные. ID в <code>…</code>."""
    repo = UserRepository()
    all_users = repo.get_all_users()
    pending = [u for u in all_users if not u.get("is_approved")]
    approved = [u for u in all_users if u.get("is_approved")]

    def display_name(u: dict) -> str:
        fn = (u.get("first_name") or "").strip()
        ln = (u.get("last_name") or "").strip()
        full = f"{fn} {ln}".strip()
        return full or (u.get("username") or "").lstrip("@") or str(u.get("user_id"))

    # админы вперёд, затем по человекочитаемому имени
    def sort_key(u: dict):
        is_admin = str(u.get("role", "")).lower() == "admin"
        return (not is_admin, display_name(u).lower())

    approved.sort(key=sort_key)

    lines: list[str] = []
    if pending:
        lines.append("<b>⏳ Пользователи, ожидающие авторизации:</b>")
        for u in pending:
            tail = f" @{escape(u['username'])}" if u.get("username") else ""
            lines.append(f"❔ <code>{u['user_id']}</code> — {escape(display_name(u))}{tail}")
        lines.append("")

    lines.append("<b>👥 Зарегистрированные пользователи:</b>\n")
    if approved:
        for u in approved:
            icon = "🔸" if str(u.get("role", "")).lower() == "admin" else "🔹"
            tail = f" @{escape(u['username'])}" if u.get("username") else ""
            lines.append(f"{icon} <code>{u['user_id']}</code> — {escape(display_name(u))}{tail}")
    else:
        lines.append("— пока никого нет")

    footer = _load_admin_users_footer()
    if footer:
        lines.append("")
        lines.append(footer)

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_admin
async def admin_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список ожидающих одобрения (подробно)."""
    repo = UserRepository()
    pend = repo.get_pending_users()
    if not pend:
        await update.message.reply_text("✅ Нет ожидающих пользователей.")
        return

    def display_name(u: dict) -> str:
        fn = (u.get("first_name") or "").strip()
        ln = (u.get("last_name") or "").strip()
        full = f"{fn} {ln}".strip()
        return full or (u.get("username") or "").lstrip("@") or str(u.get("user_id"))

    lines = ["⌛️ <b>Ожидающие:</b>"]
    for u in pend:
        tail = f" @{escape(u['username'])}" if u.get("username") else ""
        lines.append(f"{escape(display_name(u))} <code>{u['user_id']}</code>{tail}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_admin
async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Одобрить: /admin_approve <user_id> [group_key]."""
    if not context.args:
        await update.message.reply_text(
            "❌ Использование: <code>/admin_approve</code> <i>user_id</i> [<i>group_key</i>]",
            parse_mode="HTML",
        )
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return

    admin_id = update.effective_user.id if update.effective_user else None
    repo = UserRepository()
    ok = repo.approve_user(user_id, admin_id or user_id)

    msg_parts = []
    if ok:
        msg_parts.append(f"✅ Пользователь <code>{user_id}</code> одобрен")
    else:
        await update.message.reply_text(
            f"❌ Не удалось одобрить пользователя <code>{user_id}</code>",
            parse_mode="HTML",
        )
        return

    # опционально назначить группу, если передали второй аргумент
    if len(context.args) > 1:
        group_key = (context.args[1] or "").strip()
        if group_key:
            try:
                from database import group_repository as group_repo
                set_fn = getattr(group_repo, "set_user_group", None) or getattr(group_repo, "assign_user_to_group", None)
                g_ok = bool(set_fn(user_id, group_key)) if callable(set_fn) else False
                if g_ok:
                    msg_parts.append(f"(группа <code>{escape(group_key)}</code> назначена)")
                else:
                    msg_parts.append(f"(⚠️ группа <code>{escape(group_key)}</code> не назначена)")
            except Exception:
                msg_parts.append("(⚠️ нет функции назначения группы)")

    await update.message.reply_text(" ".join(msg_parts), parse_mode="HTML")


@require_admin
async def admin_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить: /admin_removeuser <user_id> (работает через UserRepository)."""
    if not context.args:
        await update.message.reply_text(
            "❌ Использование: <code>/admin_removeuser</code> <i>user_id</i>",
            parse_mode="HTML",
        )
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return

    repo = UserRepository()
    ok = repo.remove_user(user_id)

    if ok:
        await update.message.reply_text(f"🗑 Пользователь <code>{user_id}</code> удалён", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Не удалось удалить пользователя <code>{user_id}</code>.", parse_mode="HTML")

# Алиас под импорт в main.py
remove_user = admin_removeuser

@require_admin
async def admin_set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назначить группу: /admin_set_group <user_id> <group_key>."""
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: <code>/admin_set_group</code> <i>user_id</i> <i>group_key</i>", parse_mode="HTML")
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return
    group_key = context.args[1].strip()

    try:
        from database import group_repository as group_repo
    except Exception as e:
        await update.message.reply_text(f"❌ Репозиторий групп недоступен: {e}")
        return

    set_fn = _try_repo_funcs(group_repo, ("set_user_group", "assign_user_to_group", "set_group"))
    ok = bool(_safe_call(set_fn, user_id, group_key))
    if ok:
        await update.message.reply_text(f"✅ Назначена группа <code>{escape(group_key)}</code> пользователю <code>{user_id}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Не удалось назначить группу", parse_mode="HTML")


@require_admin
async def admin_unset_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Снять группу: /admin_unset_group <user_id>."""
    if not context.args:
        await update.message.reply_text("❌ Использование: <code>/admin_unset_group</code> <i>user_id</i>", parse_mode="HTML")
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return

    try:
        from database import group_repository as group_repo
    except Exception as e:
        await update.message.reply_text(f"❌ Репозиторий групп недоступен: {e}")
        return

    unset_fn = _try_repo_funcs(group_repo, ("unset_user_group", "remove_user_from_group", "unset_group"))
    ok = bool(_safe_call(unset_fn, user_id))
    if ok:
        await update.message.reply_text(f"✅ С пользователя <code>{user_id}</code> снята группа", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Не удалось снять группу", parse_mode="HTML")


@require_admin
async def admin_list_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователи в группе: /admin_list_group <group_key>."""
    if not context.args:
        await update.message.reply_text("❌ Использование: <code>/admin_list_group</code> <i>group_key</i>", parse_mode="HTML")
        return
    group_key = context.args[0].strip()

    # пробуем получить прямо из group_repository
    try:
        from database import group_repository as group_repo
    except Exception:
        group_repo = None

    rows = []
    if group_repo:
        getter = _try_repo_funcs(group_repo, ("list_users_in_group", "get_group_users", "group_users"))
        rows = _safe_call(getter, group_key) or []

    if not rows:
        # fallback: фильтрация по всем пользователям
        rows = [u for u in _get_all_users() if (u.get("group_key") or "") == group_key]

    if not rows:
        await update.message.reply_text(f"Группа <code>{escape(group_key)}</code>: — пусто", parse_mode="HTML")
        return

    lines = [f"👥 Пользователи в группе <code>{escape(group_key)}</code>:"]
    for u in rows:
        if not isinstance(u, dict) or "uid" not in u:
            u = _norm_user(u)
        lines.append(_format_user_line(u, with_icon=True))
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_admin
async def admin_update_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновление профилей (username/имена) в БД и показ результата."""
    try:
        from database import user_repository as user_repo
    except Exception as e:
        await update.message.reply_text(f"❌ Репозиторий пользователей недоступен: {e}")
        return

    updater = _try_repo_funcs(user_repo, ("update_all_users", "refresh_all_users", "admin_update_all_users"))
    res = _safe_call(updater)

    # Нет функции в репозитории или вызов не удался
    if res is None:
        await update.message.reply_text("❌ Нет функции обновления в репозитории пользователей")
        return

    # Если репозиторий возвращает целое — это количество обновлённых строк
    if isinstance(res, int):
        if res > 0:
            await update.message.reply_text(f"✅ Обновлено профилей: <b>{res}</b>", parse_mode="HTML")
        else:
            await update.message.reply_text("ℹ️ Изменений не найдено")
        return

    # На всякий случай: если вернули dict со счётчиком
    if isinstance(res, dict) and "updated" in res:
        n = int(res.get("updated") or 0)
        if n > 0:
            await update.message.reply_text(f"✅ Обновлено профилей: <b>{n}</b>", parse_mode="HTML")
        else:
            await update.message.reply_text("ℹ️ Изменений не найдено")
        return

    # Фолбэк на старую реализацию (True/False)
    if isinstance(res, bool):
        await update.message.reply_text("✅ Готово" if res else "❌ Обновление не выполнено")
        return

    # Непредвидённый формат
    await update.message.reply_text("ℹ️ Обновление выполнено, но формат ответа неизвестен")

# Алиас под импорт в main.py
async def update_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await admin_update_all_users(update, context)


@require_admin
async def admin_promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдать админ-права: /admin_promote <user_id>"""
    if not context.args:
        await update.message.reply_text("❌ Использование: <code>/admin_promote</code> <i>user_id</i>", parse_mode="HTML")
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return

    try:
        from database import user_repository as user_repo
    except Exception as e:
        await update.message.reply_text(f"❌ Репозиторий пользователей недоступен: {e}")
        return

    try_names_bool = ("set_admin", "set_is_admin")
    try_names_one  = ("promote_user", "make_admin")
    try_names_role = ("set_role", "update_role", "change_role")

    ok = False
    for name in try_names_bool:
        fn = getattr(user_repo, name, None)
        if callable(fn):
            ok = bool(_safe_call(fn, user_id, True))
            if ok is not None:
                break

    if not ok:
        for name in try_names_one:
            fn = getattr(user_repo, name, None)
            if callable(fn):
                ok = bool(_safe_call(fn, user_id))
                if ok is not None:
                    break

    if not ok:
        for name in try_names_role:
            fn = getattr(user_repo, name, None)
            if callable(fn):
                ok = bool(_safe_call(fn, user_id, "admin"))
                if ok is not None:
                    break

    if ok:
        await update.message.reply_text(f"✅ Пользователь <code>{user_id}</code> повышен до администратора", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Не удалось выдать админ-права пользователю <code>{user_id}</code>", parse_mode="HTML")


@require_admin
async def admin_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Снять админ-права: /admin_demote <user_id>"""
    if not context.args:
        await update.message.reply_text("❌ Использование: <code>/admin_demote</code> <i>user_id</i>", parse_mode="HTML")
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return

    try:
        from database import user_repository as user_repo
    except Exception as e:
        await update.message.reply_text(f"❌ Репозиторий пользователей недоступен: {e}")
        return

    try_names_bool = ("set_admin", "set_is_admin")
    try_names_one  = ("demote_user", "remove_admin")
    try_names_role = ("set_role", "update_role", "change_role")

    ok = False
    for name in try_names_bool:
        fn = getattr(user_repo, name, None)
        if callable(fn):
            ok = bool(_safe_call(fn, user_id, False))
            if ok is not None:
                break

    if not ok:
        for name in try_names_one:
            fn = getattr(user_repo, name, None)
            if callable(fn):
                ok = bool(_safe_call(fn, user_id))
                if ok is not None:
                    break

    if not ok:
        for name in try_names_role:
            fn = getattr(user_repo, name, None)
            if callable(fn):
                ok = bool(_safe_call(fn, user_id, "user"))
                if ok is not None:
                    break

    if ok:
        await update.message.reply_text(f"✅ С пользователя <code>{user_id}</code> сняты админ-права", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Не удалось снять админ-права у пользователя <code>{user_id}</code>", parse_mode="HTML")


# ===== Простой /admin_help (чтобы импорт в main.py не падал) ===============
async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Короткая справка по админ-командам пользователей."""
    footer = _load_admin_users_footer()
    await update.message.reply_text(footer, parse_mode="HTML")


# ===== Заглушки legacy-групп, чтобы не падал импорт из main.py =============

async def admin_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Legacy команды групп переехали. Используйте /admin_time_groups_*.", parse_mode="HTML")

async def admin_group_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_groups(update, context)

async def admin_group_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_groups(update, context)

async def admin_group_set_offset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_groups(update, context)

async def admin_group_set_epoch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_groups(update, context)

async def admin_group_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_groups(update, context)
