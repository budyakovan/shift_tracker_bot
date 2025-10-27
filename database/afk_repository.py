# /home/telegrambot/shift_tracker_bot/database/afk_repository.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
from zoneinfo import ZoneInfo
from typing import Set, Dict, List, Optional, Any
from datetime import datetime, timedelta

# ВАЖНО: duty_repository больше не используем!
# from database import duty_repository as duty_repo   # ← удалить

from .connection import db_connection
from database import time_repository as time_repo

# Совместимость: активные «на смене» теперь берём из shift_repository
try:
    from database.shift_repository import (
        get_on_duty_members_now as _get_on_duty_members_now,
        get_on_shift_now as _get_on_shift_now,
        is_on_shift_now as _is_on_shift_now,
    )
except Exception:
    def _get_on_duty_members_now(*args, **kwargs): return []
    def _get_on_shift_now(*args, **kwargs): return []
    def _is_on_shift_now(*args, **kwargs): return False

# Опциональные функции перераспределения/сверки (если у тебя они были в duty_repository):
# даём безопасные заглушки, чтобы код стартовал даже без них
try:
    from database.assign_repository import (  # если такого модуля нет — перейдём на заглушки ниже
        auto_assign_weighted_global_now as _auto_assign_weighted_global_now,
        reconcile_weighted_global_now as _reconcile_weighted_global_now,
    )
except Exception:
    def _auto_assign_weighted_global_now(*args, **kwargs): return 0
    def _reconcile_weighted_global_now(*args, **kwargs): return {"kept": 0, "reassigned": 0, "skipped": 0}

logger = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")


def set_afk(user_id: int,
            minutes: Optional[int] = None,
            reason: Optional[str] = None,
            chat_id: Optional[int] = None,
            message_id: Optional[int] = None,
            started_at: Optional[datetime] = None) -> None:
    started_at = started_at or datetime.utcnow()
    until_at = (started_at + timedelta(minutes=minutes)) if minutes else None
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            INSERT INTO user_afk (user_id, started_at, until_at, reason, chat_id, message_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
               SET started_at=EXCLUDED.started_at,
                   until_at=EXCLUDED.until_at,
                   reason=EXCLUDED.reason,
                   chat_id=EXCLUDED.chat_id,
                   message_id=EXCLUDED.message_id
        """, (user_id, started_at, until_at, reason, chat_id, message_id))
        db_connection.get_connection().commit()

def clear_afk(user_id: int) -> bool:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("DELETE FROM user_afk WHERE user_id=%s", (user_id,))
        db_connection.get_connection().commit()
        return cur.rowcount > 0

def get_afk(user_id: int) -> Optional[Dict[str, Any]]:
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            SELECT user_id, started_at, until_at, reason, chat_id, message_id
            FROM user_afk WHERE user_id=%s
        """, (user_id,))
        r = cur.fetchone()
    if not r: return None
    return {
        "user_id": r[0], "started_at": r[1], "until_at": r[2],
        "reason": r[3], "chat_id": r[4], "message_id": r[5]
    }

def get_afk_active(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow()
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            SELECT user_id, started_at, until_at, reason FROM user_afk
            WHERE until_at IS NULL OR until_at > %s
        """, (now,))
        rows = cur.fetchall()
    return [{"user_id": r[0], "started_at": r[1], "until_at": r[2], "reason": r[3]} for r in rows]

def _today_local(now_local: Optional[datetime]) -> datetime.date:
    if not isinstance(now_local, datetime):
        now_local = datetime.now(MSK)
    return now_local.astimezone(MSK).date()

def get_afk_user_ids(now: Optional[datetime] = None) -> Set[int]:
    """
    Множество user_id, которые ПРЯМО СЕЙЧАС AFK.
    Базируется на user_afk: until_at IS NULL или until_at > now.
    """
    ids: Set[int] = set()
    try:
        for r in (get_afk_active(now) or []):
            uid = r.get("user_id")
            if uid is None:
                continue
            try:
                ids.add(int(uid))
            except Exception:
                continue
    except Exception:
        logger.exception("get_afk_user_ids failed")
    return ids

def _is_absent_safe(user_id: int, on_date: datetime.date) -> bool:
    """ Отсутствие по отпуску/больничному (если модуль есть). """
    if _get_absence_on_date is None:
        return False
    try:
        return bool(_get_absence_on_date(int(user_id), on_date))
    except Exception:
        return False

def _build_assigned_count(on_date: datetime.date, group_key: Optional[str] = None) -> Dict[int, int]:
    """
    Кому сколько назначено на дату (опционально по группе).
    """
    counts: Dict[int, int] = {}
    try:
        rows = duty_repo.get_assignments(on_date, group_key) or []
        for r in rows:
            uid = r.get("user_id")
            if uid is None:
                continue
            try:
                uid = int(uid)
            except Exception:
                continue
            counts[uid] = counts.get(uid, 0) + 1
    except Exception:
        logger.exception("_build_assigned_count failed")
    return counts

def _duty_ref_from_row(row: dict) -> Optional[str]:
    """
    Ключ для переназначения: short_code > code > id.
    """
    sc = (row.get("short_code") or "").strip()
    if sc:
        return sc
    code = (row.get("code") or "").strip()
    if code:
        return code
    i = row.get("id")
    return str(i) if i is not None else None

def _on_duty_active_members(group_key: str, now_local: Optional[datetime]) -> List[dict]:
    """
    Те, кто СЕЙЧАС в смене по группе и не AFK, и не в отпуске/больничном.
    """
    if not isinstance(now_local, datetime):
        now_local = datetime.now(MSK)
    today = _today_local(now_local)
    afk_ids = get_afk_user_ids(now_local)

    try:
        members = duty_repo.get_on_duty_members_now(str(group_key), now_local) or []
    except TypeError:
        members = duty_repo.get_on_duty_members_now(str(group_key)) or []

    good: List[dict] = []
    for m in members:
        try:
            uid = int(m.get("user_id", 0))
        except Exception:
            continue
        if uid in afk_ids:
            continue
        if _is_absent_safe(uid, today):
            continue
        good.append(m)
    return good

def reassign_away_from_afk_now(now_local: datetime,
                               author_id: Optional[int] = None,
                               allow_global_fallback: bool = True) -> Dict[str, int]:
    """
    Перераздача обязанностей «прямо сейчас» с учётом AFK/отсутствий.
    1) Пытаемся переназначить внутри исходной группы.
    2) Если в группе нет кандидатов — и если allow_global_fallback=True —
       ищем кандидата среди всех, кто сейчас в смене (глобально).
    Кандидат = в смене сейчас, не AFK, не в отпуске/БЛ. Выбор по минимальному числу задач на сегодня.
    Возвращает: {'kept': X, 'reassigned': Y, 'skipped': Z}
    """
    stats = {"kept": 0, "reassigned": 0, "skipped": 0}

    try:
        today = _today_local(now_local)
        afk_ids = get_afk_user_ids(now_local)

        groups = time_repo.list_groups() or []
        if not groups:
            return stats

        total_assignments = 0
        total_reassigned = 0

        # Заготовим общий счётчик задач на сегодня (для глобального фолбэка)
        counts_all = _build_assigned_count(today, group_key=None)

        for g in groups:
            gkey = str(g.get("key"))

            # Кандидаты в ЭТОЙ группе
            group_candidates = _on_duty_active_members(gkey, now_local)
            group_candidate_uids: List[int] = []
            for m in group_candidates:
                try:
                    group_candidate_uids.append(int(m.get("user_id", 0)))
                except Exception:
                    continue
            group_candidate_uids = [u for u in group_candidate_uids if u]

            # Назначения в группе на сегодня
            rows = duty_repo.get_assignments(today, gkey) or []
            if not rows:
                continue

            total_assignments += len(rows)

            # Счётчик задач в рамках группы — для локального выбора
            counts_group = _build_assigned_count(today, gkey)

            for r in rows:
                uid = r.get("user_id")
                try:
                    uid = int(uid)
                except Exception:
                    stats["skipped"] += 1
                    continue

                # оставляем, если исполнитель валиден
                if uid not in afk_ids and not _is_absent_safe(uid, today):
                    continue

                duty_ref = _duty_ref_from_row(r)
                if not duty_ref:
                    stats["skipped"] += 1
                    continue

                # 1) пробуем в своей группе
                candidate_uids = [u for u in group_candidate_uids if u != uid]

                choose_counts = counts_group  # по умолчанию локальная балансировка

                # 2) если в группе никого — глобальный фолбэк
                if not candidate_uids and allow_global_fallback:
                    # соберём всех активных по всем группам
                    global_uids: List[int] = []
                    try:
                        for gg in (time_repo.list_groups() or []):
                            ggkey = str(gg.get("key"))
                            for m in _on_duty_active_members(ggkey, now_local):
                                try:
                                    u = int(m.get("user_id", 0))
                                except Exception:
                                    continue
                                if u and u != uid:
                                    global_uids.append(u)
                    except Exception:
                        pass
                    # исключим AFK/отсутствующих на сегодня (на всякий случай)
                    candidate_uids = [u for u in set(global_uids)
                                      if (u not in afk_ids and not _is_absent_safe(u, today))]
                    # при глобальном фолбэке балансируем по общему числу задач за день
                    choose_counts = counts_all

                if not candidate_uids:
                    stats["skipped"] += 1
                    continue

                # выбираем наименее загруженного кандидата
                tgt = min(candidate_uids, key=lambda u: choose_counts.get(u, 0))
                try:
                    ok, _msg = duty_repo.reassign_duty(today, gkey, duty_ref, uid, tgt)
                except TypeError:
                    ok, _msg = duty_repo.reassign_duty(today, gkey, duty_ref, uid, tgt)

                if ok:
                    stats["reassigned"] += 1
                    total_reassigned += 1
                    # обновляем счётчики нагрузки
                    choose_counts[tgt] = choose_counts.get(tgt, 0) + 1
                    # общий счётчик тоже лучше подвинуть, чтобы глобальный баланс был согласован
                    counts_all[tgt] = counts_all.get(tgt, 0) + 1
                    counts_all[uid] = max(0, counts_all.get(uid, 0) - 1)
                    # локальный счётчик уменьшаем у старого, если он у нас есть
                    counts_group[uid] = max(0, counts_group.get(uid, 0) - 1)
                else:
                    stats["skipped"] += 1

        stats["kept"] = max(0, total_assignments - total_reassigned)
        return stats

    except Exception:
        logger.exception("reassign_away_from_afk_now failed")
        return stats

def auto_assign_weighted_global_now_afk(now_local: Optional[datetime] = None,
                                        author_id: Optional[int] = None) -> Dict[str, int]:
    """
    AFK-aware «назначить на сейчас»: базовая логика + добор с учётом AFK.
    """
    if not isinstance(now_local, datetime):
        now_local = datetime.now(MSK)
    out: Dict[str, int] = {}
    try:
        try:
            base_cnt = duty_repo.auto_assign_weighted_global_now(now_local, author_id=author_id)
        except TypeError:
            try:
                base_cnt = duty_repo.auto_assign_weighted_global_now(now_local, author_id)
            except TypeError:
                base_cnt = duty_repo.auto_assign_weighted_global_now(now_local)
        out["base_assigned"] = int(base_cnt or 0)
    except Exception:
        logger.exception("auto_assign_weighted_global_now (base) failed")
        out["base_assigned"] = 0

    afk_stats = reassign_away_from_afk_now(now_local, author_id)
    for k, v in afk_stats.items():
        out[f"afk_{k}"] = v
    return out

def reconcile_weighted_global_now_afk(now_local: Optional[datetime] = None,
                                      author_id: Optional[int] = None) -> Dict[str, int]:
    """
    AFK-aware «перерасстановка на сейчас»: штатный recon + добор с учётом AFK.
    """
    if not isinstance(now_local, datetime):
        now_local = datetime.now(MSK)
    out: Dict[str, int] = {}
    try:
        stats = duty_repo.reconcile_weighted_global_now(now_local, author_id=author_id)
        for k in ("kept", "reassigned", "skipped"):
            try:
                out[k] = int(stats.get(k, 0))
            except Exception:
                out[k] = 0
    except Exception:
        logger.exception("reconcile_weighted_global_now (base) failed")
        out.update({"kept": 0, "reassigned": 0, "skipped": 0})

    afk_stats = reassign_away_from_afk_now(now_local, author_id)
    for k, v in afk_stats.items():
        out[f"afk_{k}"] = v
    return out
