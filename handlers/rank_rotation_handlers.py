# /home/telegrambot/shift_tracker_bot/handlers/rank_rotation_handlers.py
# -*- coding: utf-8 -*-
from datetime import datetime, date
from telegram import Update
from typing import Optional
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from html import escape
import logging

import database.users_repository as user_repository
from database.rank_rotation_repository import upsert_rule, get_rule, set_enabled, get_next_rotation
from database import time_repository as time_repo
from database.pair_repository import pair_stats
try:
    # Локации могут быть в отдельном модуле; пробуем подхватить, если есть
    from database import location_repository as loc_repo
except Exception:
    loc_repo = None

# вспомогательные утилиты для tolerant calls к time_repo
def _call_time_repo(fn_names, *args, **kwargs):
    for name in (fn_names if isinstance(fn_names, (list, tuple)) else [fn_names]):
        fn = getattr(time_repo, name, None)
        if callable(fn):
            return fn(*args, **kwargs)
    raise AttributeError(f"no suitable function in time_repository: {fn_names}")
from database.pair_repository import pair_stats
try:
    # Опционально: если есть репозиторий локаций — используем для автоприменения
    from database import location_repository as loc_repo
except Exception:
    loc_repo = None

def _is_admin(uid: int) -> bool:
    ur = user_repository
    try:
        return bool(getattr(ur, "is_user_admin")(uid))
    except Exception:
        return False

def _parse_date_iso(s: str) -> date | None:
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except: return None

async def admin_rank_rotation_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_set <group_key> <period_days> <YYYY-MM-DD> [on|off]
    Пример: /admin_rank_rotation_set vrn3 7 2025-10-01 on
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /admin_rank_rotation_set <group_key> <period_days> <YYYY-MM-DD> [on|off]")
        return
    gk = args[0]
    try:
        period = int(args[1])
    except Exception:
        await update.message.reply_text("period_days — целое число.")
        return
    ep = _parse_date_iso(args[2])
    if not ep:
        await update.message.reply_text("epoch в формате YYYY-MM-DD.")
        return
    enabled = True
    if len(args) >= 4:
        enabled = (args[3].lower() == "on")
    ok = upsert_rule(gk, period, ep, enabled=enabled, mode="flip_1_2")
    await update.message.reply_text("✅ Сохранено." if ok else "❌ Ошибка сохранения.")

async def admin_rank_rotation_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_show <group_key>
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Формат: /admin_rank_rotation_show <group_key>")
        return
    gk = args[0]
    r = get_rule(gk)
    if not r:
        await update.message.reply_text("Правило не найдено.")
        return

    # вычисляем ближайшую БУДУЩУЮ дату ротации по данным из репозитория
    from datetime import time as _time
    next_rot = None
    try:
        next_rot = get_next_rotation(gk)
    except Exception:
        next_rot = None

    # Добавляем время ротации (00:00 по Москве)
    next_rot_str = "—"
    if next_rot:
        next_rot_str = datetime.combine(next_rot, _time(0, 0)).strftime("%Y-%m-%d %H:%M (МСК)")

    txt = (
        f"🔁 <b>{escape(gk)}</b>\n"
        f"• режим: {escape(r['mode'])}\n"
        f"• период (дней): {r['period_days']}\n"
        f"• эпоха: {r['epoch']}\n"
        f"• следующая ротация: {next_rot_str}\n"
        f"• включено: {'да' if r['is_enabled'] else 'нет'}"
    )

    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def admin_rank_rotation_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_off <group_key> [on|off]
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Формат: /admin_rank_rotation_off <group_key> [on|off]")
        return
    gk = args[0]
    enabled = False
    if len(args) >= 2:
        enabled = (args[1].lower() == "on")
    ok = set_enabled(gk, enabled)
    await update.message.reply_text(("✅ Включено." if enabled else "✅ Выключено.") if ok else "❌ Ошибка.")

async def admin_rank_rotation_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_now <group_key> [YYYY-MM-DD]
    Смещает epoch правила парной ротации (и epoch тайм-группы) на указанную дату или на сегодня.
    Epoch в правиле сохраняет текущие mode/period и флаг включённости.
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return

    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Формат: /admin_rank_rotation_now <group_key> [YYYY-MM-DD]")
        return

    gk = args[0].strip()
    target_date: date
    if len(args) >= 2:
        d = _parse_date_iso(args[1])
        if not d:
            await update.message.reply_text("❌ Дата должна быть в формате YYYY-MM-DD.")
            return
        target_date = d
    else:
        target_date = date.today()

    r = get_rule(gk)
    if not r:
        await update.message.reply_text("❌ Правило парной ротации для этой группы не найдено. Сначала задайте его через /admin_rank_rotation_set.")
        return

    # Переносим epoch в самом правиле, сохраняя текущие параметры.
    ok_rule = upsert_rule(
        gk,
        int(r.get("period_days") or 0) or 7,
        target_date,
        enabled=bool(r.get("is_enabled")),
        mode=(r.get("mode") or "flip_1_2"),
    )
    # Для согласованности — сдвигаем epoch и у тайм-группы (best-effort).
    ok_time = _set_group_epoch_safe(gk, target_date)

    lines = [
        f"🔁 <b>Парная ротация сейчас</b> для <code>{escape(gk)}</code>",
        f"• новая epoch: {target_date}",
        f"• правило: {'✅ обновлено' if ok_rule else '❌ не удалось обновить'} (режим: {escape(r.get('mode') or 'flip_1_2')}, период: {int(r.get('period_days') or 0) or 7} дн., {'вкл' if r.get('is_enabled') else 'выкл'})",
        f"• epoch тайм-группы: {'✅ обновлена' if ok_time else '⚠️ не удалось установить'}",
        "",
        "💡 Чтобы изменения попали в план локаций:",
        f"— /loc_clear_future {escape(gk)}",
        f"— /loc_assign 14 {escape(gk)}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

def _compute_phase_info(group_key: str, d: date):
    """Диагностика фазы flip_1_2 по epoch/period тайм-группы на дату d."""
    gi = time_repo.get_group_info(str(group_key)) or {}
    epoch = gi.get("epoch")
    period = int(gi.get("period") or gi.get("rotation_period_days") or 0) or 7
    if not epoch:
        return {"ok": False, "msg": "epoch не задана", "period": period}
    try:
        delta = (d - epoch).days
    except Exception:
        # epoch может быть строкой
        try:
            ep = datetime.strptime(str(epoch), "%Y-%m-%d").date()
        except Exception:
            return {"ok": False, "msg": f"нечитаемая epoch: {epoch!r}", "period": period}
        delta = (d - ep).days
    lcd = (delta % period) + 1               # local cycle day (1..period)
    phase_idx = (delta // period) % 2        # 0 или 1
    phase = 1 if phase_idx == 0 else 2       # flip_1_2
    return {"ok": True, "epoch": epoch, "period": period, "on": d, "lcd": lcd, "phase": phase}

async def admin_rank_rotation_diag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_diag <group_key> [YYYY-MM-DD]
    Показывает epoch/period по группе и рассчитанную фазу flip_1_2 для даты.
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Формат: /admin_rank_rotation_diag <group_key> [YYYY-MM-DD]")
        return
    gk = args[0].strip()
    d = _parse_date_iso(args[1]) if len(args) >= 2 else date.today()
    info = _compute_phase_info(gk, d)
    if not info.get("ok"):
        await update.message.reply_text(f"⚠️ {escape(info.get('msg') or '')}", parse_mode=ParseMode.HTML)
        return
    txt = (f"🧪 Диагностика парной ротации для <code>{escape(gk)}</code>\n"
           f"• epoch: {info['epoch']}\n"
           f"• period: {info['period']}\n"
           f"• дата: {info['on']}\n"
           f"• local_cycle_day: {info['lcd']}\n"
           f"• фаза (flip_1_2): {info['phase']}")
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def admin_rank_rotation_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_apply <group_key> [days]
    Best-effort: очищает будущие локации и заново назначает на N дней.
    Если loc_repo недоступен — печатает подсказку с командами.
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Формат: /admin_rank_rotation_apply <group_key> [days]")
        return
    gk = args[0].strip()
    days = 14
    if len(args) >= 2:
        try:
            days = max(1, int(args[1]))
        except Exception:
            pass
    ok_clear = ok_assign = False
    if loc_repo:
        # очистка будущих
        for meth, params in [
            ("clear_future", (gk,)),
            ("clear_future_for_group", (gk,)),
        ]:
            fn = getattr(loc_repo, meth, None)
            if callable(fn):
                try:
                    fn(*params)
                    ok_clear = True
                    break
                except Exception:
                    pass
        # назначение на период
        for meth in ("assign_range", "assign_locations_range", "assign"):
            fn = getattr(loc_repo, meth, None)
            if callable(fn):
                try:
                    fn(gk, date.today(), days)
                    ok_assign = True
                    break
                except Exception:
                    pass
    if ok_clear and ok_assign:
        await update.message.reply_text(f"✅ Применено: очищено будущее и назначено на {days} дн.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            "ℹ️ Автоприменение недоступно (нет API локаций в этом билде).\n"
            f"Выполни вручную:\n/loc_clear_future {escape(gk)}\n/loc_assign {days} {escape(gk)}",
        )

def _resolve_user_ref(ref: str) -> tuple[int | None, str]:
    """
    Принимает:
      - числовой Telegram ID ("5279371925")
      - username с/без '@' ("@ddarchkv" или "ddarchkv")
    Возвращает (user_id, human_label) — где label пригоден для сообщений.
    """
    s = (ref or "").strip()
    if not s:
        return (None, "")
    # 1) если число — это user_id
    if s.isdigit():
        uid = int(s)
        try:
            # Попробуем достать профиль, чтобы красиво подписать
            prof = None
            for meth in ("get_user_by_id", "get_user", "get"):
                fn = getattr(user_repository, meth, None)
                if callable(fn):
                    prof = fn(uid)
                    if prof:
                        break
            label = f"ID {uid}"
            if prof:
                uname = (prof.get("username") or prof.get("tg_username") or "").strip()
                if uname:
                    label = f"@{uname}"
            return (uid, label)
        except Exception:
            return (uid, f"ID {uid}")

    # 2) иначе — это username
    uname = s[1:] if s.startswith("@") else s
    # сначала прямые методы поиска
    for meth in ("get_user_by_username", "find_by_username", "get_by_username"):
        fn = getattr(user_repository, meth, None)
        if callable(fn):
            u = fn(uname)
            if u:
                try:
                    return (int(u.get("user_id")), f"@{uname}")
                except Exception:
                    pass
    # фоллбэк — обойти всех
    for meth in ("get_all_users", "list_all", "list_users"):
        fn = getattr(user_repository, meth, None)
        if callable(fn):
            users = fn() or []
            for u in users:
                name = (u.get("username") or u.get("tg_username") or "").strip()
                if name.lower() == uname.lower():
                    try:
                        return (int(u.get("user_id")), f"@{uname}")
                    except Exception:
                        pass
    return (None, s)

def _get_member_pos_safe(group_key: str, uid: int) -> int | None:
    """
    Возвращает текущую базовую позицию участника в группе из time_repo.get_group_info(...).members.
    """
    try:
        gi = time_repo.get_group_info(str(group_key)) or {}
        for m in gi.get("members") or []:
            if int(m.get("user_id")) == int(uid):
                for k in ("base_pos", "pos", "position", "slot_pos"):
                    v = m.get(k)
                    if v is not None:
                        try:
                            return int(v)
                        except Exception:
                            pass
                return 0
    except Exception:
        pass
    return None

def _set_member_pos_safe(group_key: str, uid: int, pos: int) -> bool:
    """
    Ставит позицию участнику. Пробует несколько имён методов в time_repo.
    """
    candidates = [
        "set_member_pos",
        "set_pos",
        "update_member_position",
        "admin_time_groups_set_pos",
    ]
    try:
        _call_time_repo(candidates, str(group_key), int(uid), int(pos))
        return True
    except Exception:
        return False

def _set_group_epoch_safe(group_key: str, epoch: date) -> bool:
    """
    Ставит новую epoch группе. Пробует разные имена в time_repo.
    """
    candidates = [
        "set_group_epoch",
        "set_epoch",
        "admin_time_groups_set_epoch",
        "update_group_epoch",
    ]
    try:
        _call_time_repo(candidates, str(group_key), epoch)
        return True
    except Exception:
        return False

def _update_rank_rotation_epoch_if_enabled(group_key: str, new_epoch: date) -> bool | None:
    """
    Если есть включённое правило rank_rotation — переносим epoch, сохранив mode/period/enabled.
    Возвращает True/False/None (None — правила не было).
    """
    r = get_rule(str(group_key))
    if not r or not r.get("is_enabled"):
        return None
    mode = r.get("mode") or "flip_1_2"
    period = int(r.get("period_days") or 0) or 7
    ok = upsert_rule(str(group_key), period, new_epoch, enabled=True, mode=mode)
    return bool(ok)

async def pair_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pair_stats <group_key> <YYYY-MM-DD> <YYYY-MM-DD>
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Формат: /pair_stats <group_key> <date_from> <date_to>")
        return
    gk = args[0].strip()
    def _parse_date_iso(s: str):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None
    d1 = _parse_date_iso(args[1]); d2 = _parse_date_iso(args[2])
    if not d1 or not d2:
        await update.message.reply_text("Даты в формате YYYY-MM-DD.")
        return
    try:
        rows = pair_stats(gk, d1, d2) or []
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при построении отчёта: {escape(str(e), False)}", parse_mode=ParseMode.HTML)
        return
    if not rows:
        await update.message.reply_text("Данных нет.")
        return
    lines = [f"👥 Пары по группе <b>{escape(gk)}</b> за {d1}…{d2}"]
    for r in rows:
        a, b, n = int(r.get("user_a")), int(r.get("user_b")), int(r.get("days", 0))
        lines.append(f"• {a} + {b}: {n}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

# ===================== DIAG & APPLY =====================
def _compute_phase_info(group_key: str, d: date):
    """Чисто диагностически: считаем фазу flip_1_2 по epoch/period самой тайм-группы."""
    gi = time_repo.get_group_info(str(group_key)) or {}
    epoch = gi.get("epoch")
    period = int(gi.get("period") or gi.get("rotation_period_days") or 0) or 7
    if not epoch:
        return {"ok": False, "msg": "epoch не задана", "period": period}
    try:
        delta = (d - epoch).days
    except Exception:
        # если epoch приходит строкой
        from datetime import date as _d
        from datetime import datetime as _dt
        try:
            ep = _dt.strptime(str(epoch), "%Y-%m-%d").date()
        except Exception:
            return {"ok": False, "msg": f"нечитаемая epoch: {epoch!r}", "period": period}
        delta = (d - ep).days
    # локальный день цикла (1..period)
    lcd = (delta % period) + 1
    # номер «фазы» (0 или 1) — целые интервалы по period
    phase_idx = (delta // period) % 2
    phase = 1 if phase_idx == 0 else 2  # flip_1_2: 1..period → фаза 1, след. period → фаза 2
    return {"ok": True, "epoch": epoch, "period": period, "on": d, "lcd": lcd, "phase": phase}

async def admin_rank_rotation_diag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_diag <group_key> [YYYY-MM-DD]
    Показывает epoch/period по группе и рассчитанную фазу flip_1_2 для даты.
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Формат: /admin_rank_rotation_diag <group_key> [YYYY-MM-DD]")
        return
    gk = args[0].strip()
    d = _parse_date_iso(args[1]) if len(args) >= 2 else date.today()
    info = _compute_phase_info(gk, d)
    if not info.get("ok"):
        await update.message.reply_text(f"⚠️ {info.get('msg')}", parse_mode=ParseMode.HTML)
        return
    txt = (f"🧪 Диагностика парной ротации для <code>{escape(gk)}</code>\n"
           f"• epoch: {info['epoch']}\n"
           f"• period: {info['period']} дн.\n"
           f"• дата: {info['on']}\n"
           f"• local_cycle_day: {info['lcd']}\n"
           f"• фаза (flip_1_2): {info['phase']}")
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def admin_rank_rotation_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_rank_rotation_apply <group_key> [days]
    Best-effort: очищает будущие локации и заново назначает на N дней.
    Если loc_repo недоступен — печатает подсказку с командами.
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для админов.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Формат: /admin_rank_rotation_apply <group_key> [days]")
        return
    gk = args[0].strip()
    days = 14
    if len(args) >= 2:
        try:
            days = max(1, int(args[1]))
        except Exception:
            pass
    # 1) если есть API для очистки/назначения — используем
    ok_clear = ok_assign = False
    if loc_repo:
        for meth, params in [
            ("clear_future", (gk,)),
            ("clear_future_for_group", (gk,)),
        ]:
            fn = getattr(loc_repo, meth, None)
            if callable(fn):
                try:
                    fn(*params)
                    ok_clear = True
                    break
                except Exception:
                    pass
        for meth in ("assign_range", "assign_locations_range", "assign"):
            fn = getattr(loc_repo, meth, None)
            if callable(fn):
                try:
                    fn(gk, date.today(), days)
                    ok_assign = True
                    break
                except Exception:
                    pass
    if ok_clear and ok_assign:
        await update.message.reply_text(f"✅ Применено: очищено будущее и назначено на {days} дн.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            "ℹ️ Автоприменение недоступно в этом билде.\n"
            f"Выполни вручную:\n/loc_clear_future {escape(gk)}\n/loc_assign {days} {escape(gk)}",
            parse_mode=ParseMode.HTML,
        )
