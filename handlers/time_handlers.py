import logging, re, html
from datetime import datetime, date, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from utils.decorators import require_admin
from database import time_repository as time_repo
from database import group_repository
from html import escape
from logic.duty import _local_cycle_day, _phase_label, _phase_kind
from telegram.constants import ParseMode  # вверху файла, если ещё не импортирован
from handlers.help_texts import HELP_GROUPS_SHORT, HELP_TIME_PROFILES_SHORT

logger = logging.getLogger(__name__)

_SEP_PATTERN = re.compile(r"[.\-\/\s\u00A0\u2007\u202F]+")  # . - / пробел, NBSP, Figure space, NNBSP

def _parse_epoch_date(s: str) -> date:
    """
    Поддерживаем ввод с «грязными» разделителями и невидимыми пробелами.
    Примеры: 05.09.2025 / 05-09-2025 / 05/09/2025 / 05.09
    """
    if not s:
        raise ValueError("empty")

    # Нормализация: заменяем все возможные разделители на точку,
    # выкидываем лишние пробелы/невидимые символы вокруг
    s_norm = _SEP_PATTERN.sub(".", s).strip(" .")

    # Вариант без года: ДД.ММ
    m2 = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", s_norm)
    if m2:
        d, m = map(int, m2.groups())
        y = date.today().year
        return date(y, m, d)

    # Вариант с годом: ДД.ММ.ГГГГ
    m3 = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s_norm)
    if m3:
        d, m, y = m3.groups()
        return date(int(y), int(m), int(d))

    # Если вдруг прилетело что-то экзотическое — пробуем через несколько fmt
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m"):
        try:
            dt = datetime.strptime(s_norm, fmt)
            if fmt == "%d.%m":
                return date(date.today().year, dt.month, dt.day)
            return dt.date()
        except ValueError:
            pass

    raise ValueError(f"bad date: {s!r} -> {s_norm!r}")

@require_admin
async def admin_time_groups_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ожидаем как минимум 4 аргумента
    if len(context.args) < 4:
        await update.message.reply_text(
            "❌ Использование:\n"
            "/admin_time_groups_create <group_key> <profile_key> <DD.MM.YYYY|YYYY-MM-DD> <period_days> [\"Название группы\"]"
        )
        return

    group_key = context.args[0].strip()
    profile_key = context.args[1].strip()
    epoch_raw = context.args[2].strip()

    # period
    try:
        period = int(context.args[3])
        if period <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("❌ period_days должен быть положительным целым числом")
        return

    # optional name (всё, что после 4-го аргумента)
    name = " ".join(context.args[4:]).strip() if len(context.args) > 4 else ""
    # если имя обёрнуто в кавычки — уберём их
    if (name.startswith('"') and name.endswith('"')) or (name.startswith("'") and name.endswith("'")):
        name = name[1:-1].strip()
    # дефолт, если не передали
    if not name:
        name = group_key

    # нормализация даты: поддерживаем DD.MM.YYYY и YYYY-MM-DD -> сохраняем как YYYY-MM-DD
    def normalize_date(s: str) -> str:
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                pass
        # если совсем нестандартно — пробуем оставить как есть, но лучше упасть
        raise ValueError("Некорректная дата. Используй DD.MM.YYYY или YYYY-MM-DD")

    try:
        epoch_iso = normalize_date(epoch_raw)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    try:
        # ВАЖНО: расширь сигнатуру time_repo.create_time_group, чтобы принимал name=...
        # например: def create_time_group(group_key, profile_key, epoch, period, name=None): ...
        ok = time_repo.create_time_group(group_key, profile_key, epoch_iso, period, name=name)
    except ValueError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось создать/обновить группу: {e}")
        return

    # подтверждение
    gk = html.escape(group_key)
    pk = html.escape(profile_key)
    nm = html.escape(name)
    await update.message.reply_text(
        f"✅ Тайм-группа <b>{nm}</b> (<code>{gk}</code>) создана/обновлена:\n"
        f"• профиль: <code>{pk}</code>\n"
        f"• эпоха: {epoch_iso}\n"
        f"• период: {period} д.",
        parse_mode="HTML",
    )

@require_admin
async def admin_time_groups_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить пользователя в тайм-группу"""
    if len(context.args) < 3:
        await update.message.reply_text("❌ Использование: /admin_time_groups_add_user <group_key> <user_id> <pos>")
        return

    gk = context.args[0]
    uid = int(context.args[1])
    pos = int(context.args[2])

    ok = time_repo.add_user_to_group(gk, uid, pos)
    if ok:
        await update.message.reply_text(f"✅ Пользователь {uid} добавлен в группу {gk} (pos={pos})")
    else:
        await update.message.reply_text(f"❌ Не удалось добавить пользователя {uid} в группу {gk}")

@require_admin
async def admin_time_groups_remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить пользователя из тайм-группы"""
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: /admin_time_groups_remove_user <group_key> <user_id>")
        return

    gk = context.args[0]
    uid = int(context.args[1])

    ok = time_repo.remove_user_from_group(gk, uid)
    if ok:
        await update.message.reply_text(f"🗑 Пользователь {uid} удалён из группы {gk}")
    else:
        await update.message.reply_text(f"❌ Не удалось удалить пользователя {uid} из группы {gk}")

@require_admin
async def admin_time_groups_set_pos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменить позицию пользователя в тайм-группе"""
    if len(context.args) < 3:
        await update.message.reply_text("❌ Использование: /admin_time_groups_set_pos <group_key> <user_id> <pos>")
        return

    gk = context.args[0]
    uid = int(context.args[1])
    pos = int(context.args[2])

    ok = time_repo.set_user_pos(gk, uid, pos)
    if ok:
        await update.message.reply_text(f"✅ Позиция пользователя {uid} в группе {gk} изменена на {pos}")
    else:
        await update.message.reply_text("❌ Не удалось изменить позицию")

@require_admin
async def admin_time_groups_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Использование: /admin_time_groups_show <group_key>")
        return

    gk = context.args[0].strip()
    info = time_repo.get_group_info(gk)
    if not info:
        await update.message.reply_text(f"❌ Группа <b>{escape(gk)}</b> не найдена", parse_mode="HTML")
        return

    # Достаём человекочитаемое имя профиля (если есть)
    profile_key = info.get("profile_key")
    profile_name = None
    try:
        p = time_repo.get_profile_info(profile_key)
        if p:
            profile_name = p.get("name")
    except Exception:
        pass

    # Параметры группы
    epoch = info.get("epoch")                 # date
    period = int(info.get("period") or info.get("rotation_period_days") or 4)
    tz_name = info.get("tz_name") or "—"
    tz_offset_hours = int(info.get("tz_offset_hours") or 0)

    # Индекс дня цикла и дата следующего повторения
    today = date.today()
    idx = _local_cycle_day({
        "epoch": epoch,
        "offset_days": 0,
        "tz_offset_hours": tz_offset_hours,
        "period": period,
    }, today)
    phase_label = _phase_label(idx)
    days_to_reset = (period - idx) % period
    next_reset_date = today + timedelta(days=days_to_reset)

    # Заголовок в требуемом стиле
    prof_part = escape(profile_name) if profile_name else escape(profile_key or "")
    header = (
        f"⏱ Группа {escape(info.get('key'))}, профиль {prof_part}"
        + (f" ({escape(profile_key)})" if profile_name else "")
        + "\n"
        f"Epoch: {epoch}, период: {period} д., TZ: {escape(tz_name)}\n"
        f"Цикл: {idx + 1}/{period} ({escape(phase_label)}). "
        f"Следующее повторение: {next_reset_date.strftime('%d.%m.%Y')}\n"
        f"Слоты:"
    )

    # Слоты профиля: 0..N — «HH:MM–HH:MM "Название"»
    slot_lines = []
    for s in sorted(info.get("slots", []), key=lambda x: x.get("pos", 0)):
        nm = (s.get("name") or "").strip()
        # убираем лишние кавычки из базы
        if nm.startswith('"') and nm.endswith('"'):
            nm = nm[1:-1]

        nm_part = f' "{escape(nm)}"' if nm else ""
        slot_lines.append(f"{s['pos']}. {s['start']}–{s['end']}{nm_part}")

    if not slot_lines:
        slot_lines.append("— слоты не заданы")

    # Участники: `<base_pos> <user_id> Имя Фамилия @username`
    member_lines = []
    for m in info.get("members", []):
        pos = int(m.get("base_pos") or 0)
        uid = m.get("user_id")
        fn = (m.get("first_name") or "").strip()
        ln = (m.get("last_name") or "").strip()
        un = (m.get("username") or "").strip()
        name_str = " ".join([x for x in [fn, ln] if x]).strip()
        user_part = name_str if name_str else str(uid)
        if un:
            user_part += f" @{escape(un)}"
        member_lines.append(f"{pos} {uid} {escape(user_part)}")
    if not member_lines:
        member_lines.append("— участников нет")

    msg = (
        header + "\n" +
        "\n".join(slot_lines) + "\n" +
        "Участники:\n" +
        "\n".join(member_lines)
    )

    await update.message.reply_text(msg, parse_mode="HTML")

@require_admin
async def admin_time_groups_set_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить период ротации"""
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: /admin_time_groups_set_period <group_key> <days>")
        return

    gk = context.args[0]
    days = int(context.args[1])

    ok = time_repo.set_group_period(gk, days)
    if ok:
        await update.message.reply_text(f"✅ Период ротации группы {gk} = {days} д.")
    else:
        await update.message.reply_text("❌ Ошибка при установке периода")

@require_admin
async def admin_debug_date(update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /admin_debug_date <дата>")
        return
    raw = context.args[0]
    try:
        d = _parse_epoch_date(raw)
        await update.message.reply_text(f"RAW={raw!r}\nOK: {d.strftime('%d.%m.%Y')}")
    except Exception as e:
        await update.message.reply_text(f"RAW={raw!r}\nFAIL: {e}")

@require_admin
async def admin_time_groups_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список тайм-групп (+ короткая шпаргалка команд)."""
    try:
        rows = time_repo.list_groups() or []
        if not rows:
            await update.message.reply_text("Пока нет тайм-групп.")
            return

        def fmt_epoch(v):
            if isinstance(v, datetime):
                return v.date().isoformat()
            if isinstance(v, date):
                return v.isoformat()
            return str(v).strip() if v else "—"

        lines: list[str] = ["⏰ <b>Список тайм-групп:</b>", ""]

        for g in rows:
            key = g["key"]
            info = time_repo.get_group_info(key) or {}

            # данные
            raw_name = (info.get("name") or key or "").strip()
            name = html.escape(raw_name)
            key_html = html.escape(key)
            profile_key = html.escape((info.get("profile_key") or "").strip())
            epoch = fmt_epoch(info.get("epoch"))
            period = int(info.get("period") or info.get("rotation_period_days") or 8)

            tz_name = html.escape((info.get("tz_name") or info.get("tz") or "Europe/Moscow").strip())
            try:
                offset = int(info.get("tz_offset_hours") or 0)
            except Exception:
                offset = 0

            # заголовок
            header = f"👥 {name} (<code>{key_html}</code>)" if raw_name.lower().startswith("группа ") \
                     else f"👥 Группа {name} (<code>{key_html}</code>)"

            # блок инфо
            lines.append(header)
            lines.append(f"       Профиль: <code>{profile_key}</code>")
            lines.append(f"       Эпоха: {epoch}  Период: {period} дн.")
            lines.append(f"       TZ: {tz_name} ({offset}ч)")

            # участники из get_group_info -> "members"
            members = info.get("members") or []
            # сортировка по позиции и затем по ID
            members = sorted(members, key=lambda m: (m.get("base_pos", 0), m.get("user_id", 0)))

            if members:
                for m in members:
                    uid = m.get("user_id") or "—"
                    first = (m.get("first_name") or "").strip()
                    last  = (m.get("last_name") or "").strip()
                    full_name = (first + " " + last).strip() or ""
                    username = f"@{m['username']}" if m.get("username") else ""
                    full_name = html.escape(full_name)
                    # 🔹 uid — Имя @username
                    lines.append(f"🔹 <code>{uid}</code> — {full_name} {username}".rstrip())
            else:
                lines.append("")

            lines.append("")  # пустая строка после группы

        # короткая шпаргалка внизу
        lines.append(HELP_GROUPS_SHORT)

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    except Exception as e:
        logging.exception("admin_time_groups_list: %s", e)
        await update.message.reply_text("⚠️ Не удалось получить список групп.")
        raise

@require_admin
async def admin_time_profile_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все профили времени"""
    profiles = time_repo.list_profiles()
    if not profiles:
        await update.message.reply_text("❌ Профили времени не найдены")
        return
    lines = ["⌚ <b>Профили времени:</b>\n"]
    for p in profiles:
        tz = p["tz_name"] or f"MSK{int(p['tz_offset_hours']):+d}h"
        lines.append(f"🕰️ <b>{p['name']}</b> (<code>{p['key']}</code>)")
        lines.append(f"       TZ: {tz}")
    lines.append("")
    lines.append(HELP_TIME_PROFILES_SHORT)
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

@require_admin
async def admin_time_profile_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создать профиль времени"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Использование: /admin_time_profile_create <profile_key> <name...> [tz_name]\n"
            "Пример: /admin_time_profile_create vdk_12h «Владик 12ч» Europe/Moscow"
        )
        return
    profile_key = context.args[0].strip()
    args = context.args[1:]
    tz_name = None
    if args and "/" in args[-1]:
        tz_name = args[-1]
        name_parts = args[:-1]
    else:
        name_parts = args
    name = " ".join(name_parts).strip()
    try:
        time_repo.create_profile(profile_key, name, tz_name=tz_name, tz_offset_hours=0)
        await update.message.reply_text(f"✅ Профиль создан: <b>{name}</b> (<code>{profile_key}</code>)", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка создания профиля: {e}")

@require_admin
async def admin_time_profile_add_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить слот в профиль"""
    if len(context.args) < 4:
        await update.message.reply_text(
            "❌ Использование: /admin_time_profile_add_slot <profile_key> <pos> <HH:MM> <HH:MM> [name]\n"
            "Пример: /admin_time_profile_add_slot vdk_12h 0 08:00 20:00 День"
        )
        return
    profile_key = context.args[0].strip()
    try:
        pos = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ pos должен быть числом (0,1,2,...)")
        return
    start = context.args[2].strip()
    end = context.args[3].strip()
    name = " ".join(context.args[4:]).strip() if len(context.args) > 4 else None
    try:
        time_repo.add_slot(profile_key, pos, start, end, name=name)
        await update.message.reply_text(
            f"✅ Слот добавлен: проф=<code>{profile_key}</code>, pos={pos}, {start}-{end}, name={name or '—'}",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка добавления слота: {e}")

@require_admin
async def admin_time_profile_clear_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить слоты профиля"""
    if len(context.args) < 1:
        await update.message.reply_text("❌ Использование: /admin_time_profile_clear_slots <profile_key>")
        return
    profile_key = context.args[0].strip()
    try:
        n = time_repo.clear_profile_slots(profile_key)
        await update.message.reply_text(f"🗑 Удалено слотов: {n} (профиль <code>{profile_key}</code>)", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка очистки слотов: {e}")

@require_admin
async def admin_time_profile_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить тайм-профиль (если нет связанных групп)"""
    if len(context.args) < 1:
        await update.message.reply_text("❌ Использование: /admin_time_profile_delete <profile_key>")
        return

    profile_key = context.args[0].strip()

    try:
        deleted = time_repo.delete_time_profile(profile_key)
        if deleted:
            await update.message.reply_text(
                f"🗑 Профиль <b>{profile_key}</b> удалён (слоты удалены каскадно).",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"❌ Профиль <b>{profile_key}</b> не найден.",
                parse_mode="HTML",
            )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Не удалось удалить профиль <b>{profile_key}</b>. "
            f"Возможно, к нему привязаны группы.\n\nТекст ошибки: {e}",
            parse_mode="HTML",
        )

@require_admin
async def admin_time_groups_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить тайм-группу по ключу"""
    if len(context.args) < 1:
        await update.message.reply_text("❌ Использование: /admin_time_groups_delete <group_key>")
        return

    group_key = context.args[0].strip()

    try:
        deleted = time_repo.delete_time_group(group_key)
        if deleted:
            await update.message.reply_text(
                f"🗑 Группа <b>{group_key}</b> удалена (участники удалены каскадно).",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"❌ Группа <b>{group_key}</b> не найдена.",
                parse_mode="HTML",
            )
    except Exception as e:
        # маловероятно для удаления группы, но покажем человекочитаемо
        await update.message.reply_text(f"❌ Не удалось удалить группу: {e}")

@require_admin
async def admin_time_groups_set_tz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить IANA-таймзону для группы"""
    if len(context.args) < 2:
        await update.message.reply_text("❌ Использование: /admin_time_groups_set_tz <group_key> <tz_name>")
        return

    group_key = context.args[0].strip()
    tz_name = context.args[1].strip()

    try:
        ok = time_repo.set_group_tz(group_key, tz_name)
        if ok:
            await update.message.reply_text(
                f"✅ Для группы <b>{group_key}</b> установлен часовой пояс: <code>{tz_name}</code>",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"❌ Группа <b>{group_key}</b> не найдена.",
                parse_mode="HTML",
            )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка при установке TZ: {e}",
            parse_mode="HTML",
        )

@require_admin
async def admin_time_profile_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Использование: /admin_time_profile_show <profile_key>")
        return

    pk = context.args[0].strip()
    info = time_repo.get_profile_info(pk)
    if not info:
        await update.message.reply_text(f"❌ Профиль <b>{escape(pk)}</b> не найден", parse_mode="HTML")
        return

    header = f"🗂 Профиль <b>{escape(info['name'] or info['key'])}</b> (key={escape(info['key'])}, TZ={escape(info.get('tz_name') or '-')})"
    slots = info.get("slots", [])
    if not slots:
        slots_text = "— слоты не заданы"
    else:
        slots_text = "\n".join(
            f"{s['pos']}. {s['start']}–{s['end']} {escape(s.get('name') or '')}" for s in slots
        )

    msg = f"{header}\nСлоты:\n{slots_text}"
    await update.message.reply_text(msg, parse_mode="HTML")
