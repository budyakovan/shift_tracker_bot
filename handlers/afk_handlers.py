# /home/telegrambot/shift_tracker_bot/handlers/afk_handlers.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from zoneinfo import ZoneInfo

from config import config

from database.afk_repository import (
    set_afk,
    clear_afk,
    get_afk_active,
    get_afk,                 # ← ДОБАВИТЬ
    reassign_away_from_afk_now,
)


from database import time_repository as time_repo
from database.shift_repository import get_on_duty_members_now
import database.users_repository as user_repository
from database import notif_repository as notif_repo
from handlers.notif_handlers import notify_group


logger = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")

WORK_CHAT_ID = getattr(config, "WORK_CHAT_ID", None)
WORK_TOPIC_ID = getattr(config, "WORK_TOPIC_ID", None)
WORK_TOPIC_TITLE = getattr(config, "WORK_TOPIC_TITLE", "Рабочий график")

DEFAULT_AFK_MIN = 20
MENTION_PAT = re.compile(r"@([A-Za-z0-9_]{5,})")

async def _notify_afk_state(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    now_local: datetime,
    minutes: Optional[int] = None,
    reason: Optional[str] = None,
    *,
    update: Optional[Update] = None,
    kind: str = "afk"
) -> None:
    """
    Универсальное уведомление о переходе в AFK.
    - Упоминает всех текущих дежурных (кроме самого пользователя);
    - Форматирует текст (AFK на X мин / просто AFK);
    - Отправляет reply, если был update.message.
    """
    # Список текущих дежурных
    onshift_mentions: List[str] = []
    try:
        for g in (time_repo.list_groups() or []):
            gkey = str(g.get("key"))
            for m in (get_on_duty_members_now(gkey, now_local) or []):
                uid = int(m.get("user_id", 0))
                if uid == user_id:
                    continue
                un = (m.get("username") or "").strip()
                if un:
                    onshift_mentions.append(f"@{un}")
    except Exception:
        logger.exception("collect on-shift failed in _notify_afk_state")

    onshift_mentions = sorted(set(onshift_mentions), key=str.lower)
    tail = (" " + " ".join(onshift_mentions)) if onshift_mentions else ""

    # Имя пользователя
    uname = ""
    try:
        for u in (user_repository.get_all_users() or []):
            if int(u.get("user_id", 0)) == user_id:
                uname = (u.get("username") or "").strip()
                break
    except Exception:
        pass
    mention_self = f"@{uname}" if uname else ""

    # Формируем текст
    if minutes and minutes > 0:
        until_str = (now_local + timedelta(minutes=minutes)).strftime("%H:%M")
        text_html = f"🕒 {mention_self}{tail} AFK на <b>{minutes} мин</b> (до {until_str})."
    else:
        text_html = f"🕒 {mention_self}{tail} AFK."

    # Отправка: reply, если есть message
    if update and update.effective_message:
        await update.effective_message.reply_text(
            text_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    else:
        # или просто в рабочий топик (если нет контекста)
        await notify_group(context, "vrn3", text_html, kind=kind)


async def _notify_back_state(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    now_local: datetime,
    *,
    update: Optional[Update] = None,
    kind: str = "afk"
) -> None:
    """
    Универсальное уведомление о возврате с AFK.
    - Упоминает всех текущих дежурных (кроме самого пользователя);
    - Не пингует самого пользователя;
    - Отправляет reply, если есть update.message.
    """
    # Соберём текущих дежурных
    onshift_mentions: List[str] = []
    try:
        for g in (time_repo.list_groups() or []):
            gkey = str(g.get("key"))
            for m in (get_on_duty_members_now(gkey, now_local) or []):
                uid = int(m.get("user_id", 0))
                if uid == user_id:
                    continue
                un = (m.get("username") or "").strip()
                if un:
                    onshift_mentions.append(f"@{un}")
    except Exception:
        logger.exception("collect on-shift failed in _notify_back_state")

    onshift_mentions = sorted(set(onshift_mentions), key=str.lower)
    tail = (" " + " ".join(onshift_mentions)) if onshift_mentions else ""
    text_html = f"✅{tail} Вернулся на место."

    if update and update.effective_message:
        await update.effective_message.reply_text(
            text_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    else:
        # fallback — отправка через группу уведомлений
        await notify_group(context, "vrn3", text_html, kind=kind)


def _safe_en_to_ru_keep_mentions(text: str) -> str:
    """
    Перевод раскладки EN→RU, но @username НЕ трогаем.
    """
    if not text:
        return text

    _EN2RU = str.maketrans({
        'q':'й','w':'ц','e':'у','r':'к','t':'е','y':'н','u':'г','i':'ш','o':'щ','p':'з','[':'х',']':'ъ',
        'Q':'Й','W':'Ц','E':'У','R':'К','T':'Е','Y':'Н','U':'Г','I':'Ш','O':'Щ','P':'З','{':'Х','}':'Ъ',
        'a':'ф','s':'ы','d':'в','f':'а','g':'п','h':'р','j':'о','k':'л','l':'д',';':'ж',"'" :'э',
        'A':'Ф','S':'Ы','D':'В','F':'А','G':'П','H':'Р','J':'О','K':'Л','L':'Д',':':'Ж','"':'Э',
        'z':'я','x':'ч','c':'с','v':'м','b':'и','n':'т','m':'ь',',':'б','.':'ю','`':'ё','~':'Ё',
        'Z':'Я','X':'Ч','C':'С','V':'М','B':'И','N':'Т','M':'Ь','<':'Б','>':'Ю',
    })

    out = []
    last = 0
    for m in MENTION_PAT.finditer(text):
        # переводим кусок ДО упоминания
        out.append(text[last:m.start()].translate(_EN2RU))
        # само упоминание оставляем как есть
        out.append(text[m.start():m.end()])
        last = m.end()
    # хвост после последнего упоминания
    out.append(text[last:].translate(_EN2RU))
    return "".join(out)


def _extract_target_and_text(args_text: str) -> tuple[Optional[str], str]:
    """
    Из строки аргументов вытаскиваем @username (если был) и остаток текста.
    """
    if not args_text:
        return None, ""
    m = MENTION_PAT.search(args_text)
    if not m:
        return None, args_text.strip()
    uname = m.group(1)
    rest = (args_text[:m.start()] + args_text[m.end():]).strip()
    return uname, rest


_EN2RU = str.maketrans({
    'q':'й','w':'ц','e':'у','r':'к','t':'е','y':'н','u':'г','i':'ш','o':'щ','p':'з','[':'х',']':'ъ',
    'Q':'Й','W':'Ц','E':'У','R':'К','T':'Е','Y':'Н','U':'Г','I':'Ш','O':'Щ','P':'З','{':'Х','}':'Ъ',
    'a':'ф','s':'ы','d':'в','f':'а','g':'п','h':'р','j':'о','k':'л','l':'д',';':'ж',"\'":'э',
    'A':'Ф','S':'Ы','D':'В','F':'А','G':'П','H':'Р','J':'О','K':'Л','L':'Д',':':'Ж','"':'Э',
    'z':'я','x':'ч','c':'с','v':'м','b':'и','n':'т','m':'ь',',':'б','.':'ю','`':'ё','~':'Ё',
    'Z':'Я','X':'Ч','C':'С','V':'М','B':'И','N':'Т','M':'Ь','<':'Б','>':'Ю',
})


def _en_to_ru(s: str) -> str: return s.translate(_EN2RU)



AFK_PATTERNS = re.compile(r"""(?xi)
    (?:^|\b)(отош[её]л|от[оё]йду|уш[её]л
      | на\s*обед(?:е|у)?|обедать|пойду\s*отобедаю
      | перекур(ить)?|покурю
      | уш[её]л\s*смотреть\s*пгс|пгс)(?:\b|$|[.!?,…])
""")
BACK_PATTERNS = re.compile(r"""(?xi)
    (?:^|\b)
    (
        на\s*месте
      | вернул(?:ся|ась)?
      | (?:я\s*)?тут         # ловит и 'я тут', и просто 'тут'
      | теперь\s*тут
      | здесь
      | back
    )
    (?:\b|$|[.!?,…])
""")
MINUTES_PAT = re.compile(r"(\d+)\s*(мин(ут[аы]?)?|m)\b", re.IGNORECASE)
HHMM_PAT    = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

def _is_admin(uid: int) -> bool:
    ur = user_repository
    if hasattr(ur, "is_user_admin"):
        try: return bool(ur.is_user_admin(uid))
        except Exception: pass
    roles = []
    if hasattr(ur, "get_user_roles"):
        try: roles = ur.get_user_roles(uid) or []
        except Exception: roles = []
    return "admin" in {str(r).strip().lower() for r in roles}

def _name_by_uid(uid: int) -> str:
    try:
        for u in (user_repository.get_all_users() or []):
            if int(u.get("user_id", 0)) == int(uid):
                fn = (u.get("first_name") or "").strip()
                ln = (u.get("last_name") or "").strip()
                if fn or ln: return f"{fn} {ln}".strip()
                un = (u.get("username") or "").strip()
                return f"@{un}" if un else str(uid)
    except Exception:
        logger.exception("name lookup failed")
    return str(uid)

def _uid_by_username(username: str) -> Optional[int]:
    uname = username.lstrip("@").lower()
    try:
        for u in (user_repository.get_all_users() or []):
            un = (u.get("username") or "").strip().lower()
            if un and un == uname:
                return int(u.get("user_id"))
    except Exception:
        logger.exception("uid lookup failed")
    return None

def _notif_group_for_message(msg: Message) -> Optional[str]:
    try:
        ep = notif_repo.find_group_by_channel(chat_id=msg.chat_id, topic_id=msg.message_thread_id)
        if ep: return ep.get("group_key")
        ep2 = notif_repo.find_group_by_channel(chat_id=msg.chat_id, topic_id=None)
        if ep2: return ep2.get("group_key")
    except Exception:
        logger.exception("notif lookup failed")
    return None

def _detect_future_intent(text: str, now_local: datetime, min_delta_minutes: int = 5) -> Optional[datetime]:
    """
    Возвращает локальный datetime планируемого ухода, если в тексте есть 'в HH[: .]MM'
    и это время позже текущего более чем на min_delta_minutes. Иначе None.
    Примеры: 'в 15 00', 'в 15:00', 'в 9.30'
    """
    try:
        m = re.search(r"(?xi)\bв\s*([01]?\d|2[0-3])(?:[:.\s]?([0-5]\d))\b", text or "")
        if not m:
            return None
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        start = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start <= now_local:
            start += timedelta(days=1)
        if (start - now_local).total_seconds() > min_delta_minutes * 60:
            return start
    except Exception:
        logger.exception("_detect_future_intent failed")
    return None


def _parse_duration(text: str, now_local: datetime) -> Optional[int]:
    m = MINUTES_PAT.search(text or "")
    if m:
        try: return int(m.group(1))
        except Exception: pass
    if "до" in (text or "").lower():
        hm = HHMM_PAT.search(text or "")
        if hm:
            hh, mm = int(hm.group(1)), int(hm.group(2))
            until = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if until <= now_local: until += timedelta(days=1)
            return max(1, int((until - now_local).total_seconds() // 60))
    return None

def _to_msk(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    try: return dt.astimezone(MSK)
    except Exception: return dt

def _fmt_hhmm(dt: Optional[datetime]) -> str:
    d = _to_msk(dt)
    return d.strftime("%H:%M") if isinstance(d, datetime) else "—"

def _collect_on_shift_usernames(now_local: datetime, exclude_uid: Optional[int] = None) -> List[str]:
    names: Dict[str, bool] = {}
    try:
        for g in (time_repo.list_groups() or []):
            gkey = str(g.get("key"))
            for m in (get_on_duty_members_now(gkey, now_local) or []):
                uid = int(m.get("user_id", 0))
                if exclude_uid is not None and uid == int(exclude_uid): continue
                uname = (m.get("username") or "").strip()
                if uname: names[f"@{uname}"] = True
    except Exception:
        logger.exception("collect on-shift failed")
    return sorted(names.keys(), key=str.lower)

def _group_keys_for_user(now_local: datetime, user_id: int) -> List[str]:
    keys: List[str] = []
    try:
        for g in (time_repo.list_groups() or []):
            gkey = str(g.get("key"))
            for m in (get_on_duty_members_now(gkey, now_local) or []):
                if int(m.get("user_id", 0)) == int(user_id):
                    keys.append(gkey); break
    except Exception:
        logger.exception("group_keys_for_user failed")
    return keys

async def _emit_afk(update: Update,
                    context: ContextTypes.DEFAULT_TYPE,
                    now_local: datetime,
                    subject_user_id: int,
                    text_html: str,
                    kind: str = "afk",
                    gkeys_override: Optional[List[str]] = None) -> None:
    sent_any = False
    try:
        gkeys = gkeys_override if gkeys_override is not None else _group_keys_for_user(now_local, subject_user_id)
        for gk in gkeys:
            ok = await notify_group(context, gk, text_html, kind=kind)
            if ok:
                sent_any = True
    except Exception:
        logger.exception("emit_afk failed")
    if not sent_any and update.effective_message:
        await update.effective_message.reply_text(
            text_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )

# ---- AFK командЫ -----------------------------------------------------------

async def cmd_afk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    author = update.effective_user
    now_local = datetime.now(MSK)

    raw_text = " ".join((context.args or [])).strip()
    target_uname, rest_raw = _extract_target_and_text(raw_text)

    # Кого помечаем AFK
    if target_uname:
        target_uid = _uid_by_username(target_uname)
        if target_uid is None:
            await update.message.reply_text(f"❌ Не нашёл пользователя @{target_uname}.")
            return

        # Права
        from database import time_repository as time_repo
        from database.shift_repository import get_on_duty_members_now
        try:
            from database import users_repository as ur
            is_admin = bool(getattr(ur, "is_user_admin", lambda x: False)(author.id))
        except Exception:
            is_admin = False

        if not is_admin:
            share = False
            for g in (time_repo.list_groups() or []):
                gkey = str(g.get("key"))
                mems = get_on_duty_members_now(gkey, now_local) or []
                ids = {int(m.get("user_id", 0)) for m in mems}
                if author.id in ids and target_uid in ids:
                    share = True
                    break
            if not share:
                await update.message.reply_text(
                    "⛔ Недостаточно прав: можно ставить AFK только сотруднику из вашей активной группы."
                )
                return

        subject_uid = target_uid
        text_for_minutes = _safe_en_to_ru_keep_mentions(rest_raw)
    else:
        subject_uid = author.id
        text_for_minutes = _safe_en_to_ru_keep_mentions(raw_text)

    # минуты: «/afk 10 …» или «… на 10 минут …» или «до 13:45»
    minutes = None
    m = re.search(r"(\d+)\s*(мин(ут[аы]?)?|m)?\b", text_for_minutes, flags=re.IGNORECASE)
    if m:
        try:
            minutes = max(1, int(m.group(1)))
        except Exception:
            minutes = None
    if minutes is None:
        hhmm = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text_for_minutes)
        if hhmm:
            hh, mm = int(hhmm.group(1)), int(hhmm.group(2))
            until = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if until <= now_local:
                until += timedelta(days=1)
            minutes = max(1, int((until - now_local).total_seconds() // 60))

    reason = (text_for_minutes or None)
    if reason and len(reason) > 120:
        reason = reason[:117] + "…"

    set_afk(
        user_id=subject_uid,
        minutes=minutes or 0,  # 0/None = без таймера
        reason=reason,
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.id,
    )

    # Единое уведомление «ушёл» (упоминаем всех дежурных)
    await _notify_afk_state(context, subject_uid, now_local, minutes, reason, update=update, kind="afk")

    # Напоминание на конец периода (если есть таймер)
    if minutes and minutes > 0:
        try:
            delay_sec = max(2, minutes * 60)
            job_name = f"afk_rem_{subject_uid}_{update.effective_message.id}"
            context.job_queue.run_once(
                _afk_reminder_job,
                when=timedelta(seconds=delay_sec),
                data={
                    "chat_id": update.effective_chat.id,
                    "topic_id": getattr(update.effective_message, "message_thread_id", None),
                    "user_id": subject_uid,
                },
                name=job_name,
                chat_id=update.effective_chat.id,
            )
            logger.debug("Scheduled AFK end reminder name=%s in %ss", job_name, delay_sec)
        except Exception:
            logger.exception("schedule AFK reminder (cmd_afk) failed")

    # Мягкая перераздача
    try:
        reassign_away_from_afk_now(now_local, author_id=author.id)
    except Exception:
        logger.exception("AFK-aware reassign after /afk failed")

async def cmd_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /back [@username]
    Админ может снять AFK с любого пользователя.
    Не-админ — только если и он, и целевой пользователь сейчас в одной активной группе.
    Без @username — снимаем AFK у самого автора.
    """
    author = update.effective_user
    now_local = datetime.now(MSK)

    raw_text = " ".join((context.args or [])).strip()
    target_uname, _ = _extract_target_and_text(raw_text)

    # Определяем цель
    if target_uname:
        target_uid = _uid_by_username(target_uname)
        if target_uid is None:
            await update.message.reply_text(f"❌ Не нашёл пользователя @{target_uname}.")
            return

        # Права как в /afk
        try:
            from database import users_repository as ur
            is_admin = bool(getattr(ur, "is_user_admin", lambda x: False)(author.id))
        except Exception:
            is_admin = False

        if not is_admin:
            share = False
            try:
                for g in (time_repo.list_groups() or []):
                    gkey = str(g.get("key"))
                    mems = get_on_duty_members_now(gkey, now_local) or []
                    ids = {int(m.get("user_id", 0)) for m in mems}
                    if author.id in ids and target_uid in ids:
                        share = True
                        break
            except Exception:
                share = False
            if not share:
                await update.message.reply_text(
                    "⛔ Недостаточно прав: можно снимать AFK только у сотрудника из вашей активной группы."
                )
                return

        subject_uid = target_uid
        is_self = (subject_uid == author.id)
        subject_label = f"@{target_uname}"
    else:
        subject_uid = author.id
        is_self = True
        subject_label = "ты"

    ok = clear_afk(subject_uid)

    if ok:
        # Единое уведомление «вернулся» (упоминаем дежурных, без пользователя)
        await _notify_back_state(context, subject_uid, now_local, update=update, kind="afk")
    else:
        if is_self:
            await update.message.reply_text("ℹ️ Ты и так не был AFK.")
        else:
            await update.message.reply_text(f"ℹ️ У {subject_label} не было AFK.")

    # Добалансировать
    try:
        reassign_away_from_afk_now(now_local, author_id=author.id)
    except Exception:
        logger.exception("AFK-aware reassign after /back failed")


async def cmd_afk_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now_local = datetime.now(MSK)
    rows = get_afk_active()
    if not rows:
        await update.message.reply_text("Никто не AFK."); return
    lines = ["<b>Сейчас AFK:</b>"]
    for r in rows:
        uid = int(r.get("user_id"))
        name = _name_by_uid(uid)
        started = r.get("started_at") or r.get("created_at")
        until = r.get("until_at")
        desc = r["reason"] if r.get("reason") else "временно отсутствует"
        t_from = _fmt_hhmm(started); t_to = _fmt_hhmm(until)
        when_tail = f" (с {t_from} до {t_to})" if (t_from != "—" or t_to != "—") else ""
        lines.append(f"👤 {name} — {desc}{when_tail}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def _afk_plan_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Напоминание за 5 минут до планируемого ухода: предлагаем нажать /afk N.
    """
    try:
        data = context.job.data or {}
        chat_id = int(data["chat_id"])
        topic_id = data.get("topic_id")
        user_id = int(data["user_id"])
        start_ts = float(data["start_ts"])      # unix timestamp планового ухода
        planned_minutes = int(data.get("planned_minutes") or DEFAULT_AFK_MIN)

        # @mention (если есть username)
        mention = ""
        try:
            for u in (user_repository.get_all_users() or []):
                if int(u.get("user_id", 0)) == user_id:
                    un = (u.get("username") or "").strip()
                    if un:
                        mention = f"@{un}"
                    break
        except Exception:
            pass

        start_dt = datetime.fromtimestamp(start_ts, MSK)
        hhmm = start_dt.strftime("%H:%M")

        text = (
            f"⏳ {mention + ', ' if mention else ''}через 5 минут планировался уход в {hhmm}. "
            f"Если актуально — нажми /afk {planned_minutes} (или укажи своё время)."
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            message_thread_id=topic_id if topic_id else None,
            disable_web_page_preview=True,
        )
        logger.debug("AFK plan reminder sent: user_id=%s at %s", user_id, hhmm)
    except Exception:
        logger.exception("_afk_plan_reminder_job failed")


async def _afk_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Напоминание по окончании таймера AFK:
    - пингуем ТОЛЬКО самого пользователя (reply на его исходное сообщение, если оно известно);
    - без упоминаний остальных.
    """
    try:
        data = context.job.data or {}
        chat_id = int(data.get("chat_id"))
        topic_id = data.get("topic_id")
        user_id = int(data.get("user_id"))

        from database.afk_repository import get_afk
        rec = get_afk(user_id)
        if not rec:
            return  # снят вручную
        until_at = rec.get("until_at")
        if until_at is None or until_at > datetime.utcnow():
            return  # ещё рано/без таймера

        reply_to_message_id = rec.get("message_id")

        mention = ""
        try:
            for u in (user_repository.get_all_users() or []):
                if int(u.get("user_id", 0)) == user_id:
                    un = (u.get("username") or "").strip()
                    if un:
                        mention = f"@{un}"
                    break
        except Exception:
            pass

        text = f"⏰ {mention}{',' if mention else ''} время AFK истекло. Вернулся? Нажми /back, пожалуйста."

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            message_thread_id=topic_id if topic_id else None,
            disable_web_page_preview=True,
            reply_to_message_id=reply_to_message_id if reply_to_message_id else None,
        )
        logger.debug("AFK end reminder sent to user_id=%s (reply_to=%s)", user_id, reply_to_message_id)
    except Exception:
        logger.exception("AFK reminder job failed")


async def on_work_topic_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Пассивный слушатель сообщений:
    - ловим триггеры AFK/Back в свободном тексте;
    - реагируем ТОЛЬКО если текущий чат/топик помечен kind='listen';
    - AFK без минут — ставим без таймера; с минутами — ставим таймер и планируем напоминание;
    - «ушёл/вернулся» — упоминаем всех дежурных; остальные уведомления — только автору;
    - после AFK/Back вызываем мягкую перераздачу.
    """
    msg = update.effective_message
    if not msg or not msg.text:
        return

    # слушаем только там, где kind='listen'
    try:
        gkey_listen = notif_repo.resolve_listen_group(msg.chat_id, msg.message_thread_id)
    except Exception:
        logger.exception("resolve_listen_group failed")
        gkey_listen = None

    if not gkey_listen:
        logger.debug("AFK passive: skip chat_id=%s topic_id=%s (no listen binding)", msg.chat_id, msg.message_thread_id)
        return

    now_local = datetime.now(MSK)
    text_raw = msg.text.strip()
    text_ru = _safe_en_to_ru_keep_mentions(text_raw)

    # BACK?
    if BACK_PATTERNS.search(text_ru):
        ok = clear_afk(update.effective_user.id)
        if ok:
            await _notify_back_state(context, update.effective_user.id, now_local, update=update, kind="afk")
            try:
                reassign_away_from_afk_now(now_local, author_id=update.effective_user.id)
            except Exception:
                logger.exception("AFK-aware reassign after passive back failed")
        else:
            await msg.reply_text("ℹ️ Ты и так не был AFK.")
        return

    # AFK?
    if AFK_PATTERNS.search(text_ru):
        # план на будущее?
        future_start: Optional[datetime] = None
        try:
            m_time = re.search(r"(?xi)\bв\s*([01]?\d|2[0-3])(?:[:.\s]?([0-5]\d))\b", text_ru or "")
            if m_time:
                hh = int(m_time.group(1))
                mm = int(m_time.group(2) or 0)
                candidate = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if candidate <= now_local:
                    candidate += timedelta(days=1)
                if (candidate - now_local).total_seconds() > 5 * 60:
                    future_start = candidate
        except Exception:
            logger.exception("future intent detection failed")

        if future_start is not None:
            planned_minutes = _parse_duration(text_ru, now_local) or DEFAULT_AFK_MIN
            hhmm = future_start.strftime("%H:%M")
            await msg.reply_text(
                f"📝 Понял: планируешь уйти в <b>{hhmm}</b>. "
                f"Напомню за 5 минут. В момент ухода нажми <code>/afk {planned_minutes}</code> "
                f"(или укажи своё время).",
                parse_mode=ParseMode.HTML,
            )
            try:
                remind_at = future_start - timedelta(minutes=5)
                delay_sec = max(2, int((remind_at - now_local).total_seconds()))
                job_name = f"afk_plan_{update.effective_user.id}_{int(future_start.timestamp())}"
                context.job_queue.run_once(
                    _afk_plan_reminder_job,
                    when=timedelta(seconds=delay_sec),
                    data={
                        "chat_id": msg.chat_id,
                        "topic_id": msg.message_thread_id,
                        "user_id": update.effective_user.id,
                        "start_ts": future_start.timestamp(),
                        "planned_minutes": planned_minutes,
                    },
                    name=job_name,
                    chat_id=msg.chat_id,
                )
                logger.debug(
                    "Scheduled AFK plan reminder name=%s in %ss (now=%s future=%s)",
                    job_name, delay_sec, now_local.isoformat(), future_start.isoformat()
                )
            except Exception:
                logger.exception("schedule AFK plan reminder failed")
            return

        # минуты из текста (или None)
        minutes = _parse_duration(text_ru, now_local)

        # причина (чуть обрежем)
        reason = text_ru
        if reason and len(reason) > 120:
            reason = reason[:117] + "…"

        set_afk(
            user_id=update.effective_user.id,
            minutes=(minutes or 0),
            reason=reason,
            chat_id=msg.chat_id,
            message_id=msg.id,
        )

        # Единое уведомление «ушёл» (упоминаем всех дежурных)
        await _notify_afk_state(context, update.effective_user.id, now_local, minutes, reason, update=update, kind="afk")

        # Планируем напоминание на конец периода
        if minutes:
            try:
                delay_sec = max(2, minutes * 60)
                job_name = f"afk_rem_{update.effective_user.id}_{msg.id}"
                context.job_queue.run_once(
                    _afk_reminder_job,
                    when=timedelta(seconds=delay_sec),
                    data={
                        "chat_id": msg.chat_id,
                        "topic_id": msg.message_thread_id,
                        "user_id": update.effective_user.id,
                    },
                    name=job_name,
                    chat_id=msg.chat_id,
                )
                logger.debug("Scheduled AFK end reminder name=%s in %ss", job_name, delay_sec)
            except Exception:
                logger.exception("schedule AFK reminder failed")

        # Мягкая перераздача
        try:
            reassign_away_from_afk_now(now_local, author_id=update.effective_user.id)
        except Exception:
            logger.exception("AFK-aware reassign after passive afk failed")
