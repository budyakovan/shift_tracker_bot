# /home/telegrambot/shift_tracker_bot/handlers/admin_handlers.py
# -*- coding: utf-8 -*-
"""
Админ-хендлеры пользователей (компактный вывод).

ЗА ЧТО ОТВЕЧАЕТ ФАЙЛ:
— Реализует Telegram-хендлеры для админских операций с пользователями: список, «ожидающие», одобрение, назначение/снятие групп, удаление, повышение/понижение до админа, служебное обновление профилей.
— Выводит данные в «компактном» HTML-формате: ID оборачиваются в <code>…</code> для удобного копирования, есть блок «Доступные команды».
— Абстрагируется от конкретной реализации репозитория: аккуратно ищет функции по нескольким возможным именам и подбирает сигнатуры вызова, чтобы работать с разными кодовыми базами.
— Минимизирует связность: многие операции выполняются через безопасные вызовы (_safe_call), а функции поиска (_try_repo_funcs) и подбора сигнатур (_try_signatures) позволяют не падать при несовпадении API репозитория.
— Содержит fallback-логику:
   * «ожидающие» пользователи определяются через признак is_approved=False из общего списка (не требуется отдельный pending-метод),
   * краткая справка берётся из help_texts, без чтения файлов с диска,
   * есть алиасы remove_user / update_all_users и заглушки legacy-групп для совместимости с импортами из main.py.

ФОРМАТ ВЫВОДА:
— В списках пользователи сортируются: админы сверху, затем по человекочитаемому имени.
— В строках показываются иконки (👑/👤/🔸/🔹), ID в <code>, имя (или username), безопасно экранированные.

БЕЗОПАСНОСТЬ И УСТОЙЧИВОСТЬ:
— Все внешние вызовы репозиториев обёрнуты в try/except с логированием; TypeError обрабатывается отдельно, с попыткой подставить ведущий None для conn/db.
— Любой сбой в репозитории не роняет хендлер: пользователю возвращается понятное сообщение об ошибке.

СОВЕТЫ ПО ПОДДЕРЖКЕ:
— При добавлении новых функций репозитория: расширяйте кортежи имён в _try_repo_funcs / *_names_* списках.
— Если репозиторий ожидает другие сигнатуры, добавляйте варианты в _try_signatures / _call_repo_variants.
— Не меняйте логику в хендлерах без необходимости: весь «клей» с репозиторием сосредоточен в утилитах выше.

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
from typing import Any, Iterable, Optional, Callable

from telegram import Update
from telegram.ext import ContextTypes

from utils.decorators import require_admin
import database.users_repository as user_repository
from handlers.help_texts import HELP_USERS_SHORT
logger = logging.getLogger(__name__)

def _load_admin_users_footer() -> str:
    # Фолбэк-загрузка краткой справки: берём из help_texts (без файловой системы).
    return HELP_USERS_SHORT

def _norm_user(u: Any) -> dict[str, Any]:
    """Приводим запись пользователя к унифицированному виду.
    Допустимы как dict-объекты, так и объекты с атрибутами.
    Поля ищутся «по нескольким вариантам имён», берётся первое непустое.
    """
    def g(obj, *keys, default=None):
        # Универсальный геттер по альтернативным ключам/атрибутам.
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
    # «Одобрен» — либо по булевым полям, либо по человекочитаемому статусу.
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
        "status": status,  # нормализованный «текстовый» статус (если есть)
    }

def _try_repo_funcs(module, names: Iterable[str]) -> Optional[Callable[..., Any]]:
    """Вернёт первую существующую функцию из набора имён.
    Используется для совместимости с разными вариантами API.
    """
    for n in names:
        fn = getattr(module, n, None)
        if callable(fn):
            return fn
    return None

def _safe_call(fn: Optional[Callable[..., Any]], *args, **kwargs) -> Any:
    """
    Безопасно вызываем функции репозитория.
    — Возвращает None при ошибках, чтобы не падали хендлеры.
    — Особая обработка TypeError: если первый параметр похож на conn/db/session,
      пробуем подставить ведущий None.
    """
    if fn is None:
        return None
    try:
        return fn(*args, **kwargs)
    except TypeError as e:
        # Попытка угадать необходимость ведущего conn/db аргумента.
        try:
            sig = inspect.signature(fn)
            params = list(sig.parameters.values())

            # Если метод bound (у инстанса), «self» пропускаем.
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
    # Форматируем одну строку пользователя для HTML-ответа.
    icon = "👑" if u.get("is_admin") else "👤"
    uid = u.get("uid")
    name = escape((u.get("name") or "").strip()) or str(uid)
    uname = u.get("username")
    piece = f"<code>{uid}</code> — {name}"
    if uname:
        piece += f" @{escape(uname)}"
    return f"{icon} {piece}" if with_icon else piece


def _get_all_users() -> list[dict[str, Any]]:
    try:
        repo = user_repository
        raw = repo.get_all_users() or []
    except Exception as e:
        logger.error("get_all_users via users_repository failed: %s", e)
        return []
    # Нормализация к вашему формату
    return [_norm_user(x) for x in raw if x is not None]


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
    Универсальный перебор сигнатур репозитория для bool-операций.
    Пробуем: (user_id), (user_id, True), (None, user_id), (None, user_id, True).
    Возвращаем:
      — True/False по результату,
      — True если функция ничего не вернула (считаем успехом),
      — None если ни один вариант не подошёл/упал.
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
            # Отсутствие возвращаемого значения трактуем как успех.
            return True if res is None else bool(res)
        except TypeError:
            continue
        except Exception as e:
            logger.warning("Repo call failed for %s%r: %s", getattr(fn, "__name__", fn), args, e)
            continue
    return None

def _try_signatures(fn: Callable[..., Any], argsets: list[tuple]) -> Optional[bool]:
    """
    Перебираем наборы аргументов и вариант с ведущим None (conn/db).
    Результат:
      — bool по возвращаемому значению,
      — True, если функция ничего не вернула,
      — None, если ничего не подошло.
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
    Одобряем пользователя через любое из поддерживаемых имён репозитория.
    Репозиторий может ожидать:
      - approve_user(user_id)
      - approve_user(user_id, admin_id)
      - и те же варианты с ведущим conn/None.
    """
    try:
        import database.users_repository as user_repo
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
    Если в репозитории есть явная функция очистки «ожидающих» — используем её.
    Сигнатура ожидается как (user_id) [+ возможный ведущий None].
    """
    try:
        import database.users_repository as user_repo
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
    """Назначение группы пользователю через group_repository (с поддержкой разных имён)."""
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

@require_admin
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список пользователей: сначала ожидающие, затем одобренные. ID в <code>…</code>.
    Группировка и компактный формат для удобного обзора.
    """
    repo = user_repository
    all_users = repo.get_all_users()
    pending = [u for u in all_users if not u.get("is_approved")]
    approved = [u for u in all_users if u.get("is_approved")]

    def display_name(u: dict) -> str:
        # Человекочитаемое имя: first+last, иначе username, иначе user_id.
        fn = (u.get("first_name") or "").strip()
        ln = (u.get("last_name") or "").strip()
        full = f"{fn} {ln}".strip()
        return full or (u.get("username") or "").lstrip("@") or str(u.get("user_id"))

    # Сортировка: админы вперёд, затем по имени (регистронезависимо).
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

    # «Хвост» со справкой по командам
    footer = _load_admin_users_footer()
    if footer:
        lines.append("")
        lines.append(footer)

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

@require_admin
async def admin_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список ожидающих одобрения (подробно)."""
    repo = user_repository
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
    """Одобрить: /admin_approve <user_id> [group_key].
    Поддерживает опциональное назначение группы вторым аргументом.
    """
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
    repo = user_repository
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

    # Опционально назначить группу (второй аргумент).
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
    """Удалить: /admin_removeuser <user_id>.
    Алиас remove_user для совместимости с импортами.
    """
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

    repo = user_repository
    ok = repo.remove_user(user_id)

    if ok:
        await update.message.reply_text(f"🗑 Пользователь <code>{user_id}</code> удалён", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Не удалось удалить пользователя <code>{user_id}</code>.", parse_mode="HTML")

@require_admin
async def admin_update_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Служебное обновление профилей: username/имена из Telegram.
    Ожидается, что репозиторий вернёт:
      — int (сколько обновлено),
      — (updated, inserted),
      — {"updated": X, "inserted": Y}.
    """
    try:
        from database import users_repository as repo_mod
    except Exception as e:
        await update.message.reply_text(f"❌ Репозиторий пользователей недоступен: {e}")
        return

    # Ищем метод обновления под разными именами — совместимость с разными репозиториями.
    updater = None
    for name in ("update_all_users", "refresh_all_users", "admin_update_all_users"):
        updater = getattr(repo_mod, name, None)
        if callable(updater):
            break

    if not updater:
        await update.message.reply_text("❌ Нет функции обновления в репозитории пользователей")
        return

    try:
        result = updater()
    except TypeError:
        # Возможно, метод ожидает context/db/None первым аргументом.
        try:
            result = updater(None)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка запуска обновления: {e}")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка запуска обновления: {e}")
        return

    # Нормализуем результат в (updated, inserted).
    updated = inserted = None
    if isinstance(result, dict):
        updated = int(result.get("updated", 0))
        inserted = int(result.get("inserted", 0))
    elif isinstance(result, (tuple, list)):
        if len(result) >= 2:
            updated = int(result[0])
            inserted = int(result[1])
        elif len(result) == 1:
            updated = int(result[0])
    elif isinstance(result, int):
        updated = result

    if updated is None and inserted is None:
        await update.message.reply_text("🔄 Обновление профилей инициировано")
    else:
        parts = []
        if updated is not None:
            parts.append(f"обновлено: <b>{updated}</b>")
        if inserted is not None:
            parts.append(f"новых: <b>{inserted}</b>")
        await update.message.reply_text("✅ Обновление завершено — " + ", ".join(parts), parse_mode="HTML")

@require_admin
async def admin_promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Использование: <code>/admin_promote</code> <i>user_id</i>", parse_mode="HTML")
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return

    admin_id = update.effective_user.id if update.effective_user else None

    # 1) Пытаемся через текущий репозиторий (класс)
    repo = user_repository
    ok = False
    try:
        if hasattr(repo, "promote_user") and callable(repo.promote_user):
            ok = bool(repo.promote_user(user_id, admin_id))
        elif hasattr(repo, "set_admin") and callable(repo.set_admin):
            ok = bool(repo.set_admin(user_id, True, admin_id))
        elif hasattr(repo, "set_role") and callable(repo.set_role):
            ok = bool(repo.set_role(user_id, "admin", admin_id))
    except Exception as e:
        logger.warning("Repo class promote failed: %s", e)

    # 2) Fallback: поддержка старых код-баз (модуль user_repository)
    if not ok:
        try:
            import database.users_repository as user_repo  # может отсутствовать в этой кодовой базе
        except Exception:
            user_repo = None

        if user_repo:
            try_names_bool = ("set_admin", "set_is_admin")
            try_names_one  = ("promote_user", "make_admin")
            try_names_role = ("set_role", "update_role", "change_role")

            for name in try_names_bool:
                fn = getattr(user_repo, name, None)
                if callable(fn):
                    ok = bool(fn(user_id, True))
                    if ok:
                        break
            if not ok:
                for name in try_names_one:
                    fn = getattr(user_repo, name, None)
                    if callable(fn):
                        ok = bool(fn(user_id))
                        if ok:
                            break
            if not ok:
                for name in try_names_role:
                    fn = getattr(user_repo, name, None)
                    if callable(fn):
                        ok = bool(fn(user_id, "admin"))
                        if ok:
                            break

    if ok:
        await update.message.reply_text(f"✅ Пользователь <code>{user_id}</code> повышен до администратора", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Не удалось выдать админ-права пользователю <code>{user_id}</code>", parse_mode="HTML")

@require_admin
async def admin_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Использование: <code>/admin_demote</code> <i>user_id</i>", parse_mode="HTML")
        return
    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ user_id должен быть числом")
        return

    admin_id = update.effective_user.id if update.effective_user else None

    repo = user_repository
    ok = False
    try:
        if hasattr(repo, "demote_user") and callable(repo.demote_user):
            ok = bool(repo.demote_user(user_id, admin_id))
        elif hasattr(repo, "set_admin") and callable(repo.set_admin):
            ok = bool(repo.set_admin(user_id, False, admin_id))
        elif hasattr(repo, "set_role") and callable(repo.set_role):
            ok = bool(repo.set_role(user_id, "user", admin_id))
    except Exception as e:
        logger.warning("Repo class demote failed: %s", e)

    if not ok:
        try:
            import database.users_repository as user_repo
        except Exception:
            user_repo = None

        if user_repo:
            try_names_bool = ("set_admin", "set_is_admin")
            try_names_one  = ("demote_user", "remove_admin")
            try_names_role = ("set_role", "update_role", "change_role")

            for name in try_names_bool:
                fn = getattr(user_repo, name, None)
                if callable(fn):
                    ok = bool(fn(user_id, False))
                    if ok:
                        break
            if not ok:
                for name in try_names_one:
                    fn = getattr(user_repo, name, None)
                    if callable(fn):
                        ok = bool(fn(user_id))
                        if ok:
                            break
            if not ok:
                for name in try_names_role:
                    fn = getattr(user_repo, name, None)
                    if callable(fn):
                        ok = bool(fn(user_id, "user"))
                        if ok:
                            break

    if ok:
        await update.message.reply_text(f"✅ С пользователя <code>{user_id}</code> сняты админ-права", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Не удалось снять админ-права у пользователя <code>{user_id}</code>", parse_mode="HTML")
