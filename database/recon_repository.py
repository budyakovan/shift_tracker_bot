# shift_tracker_bot/database/recon_repository.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging

from .connection import db_connection
from . import users_repository as users_repo
from . import duty_repository as duty_repo
from . import time_repository as time_repo
from config import config

logger = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")

RECON_SOFT   = "SOFT"
RECON_FAMILY = "FAMILY"
RECON_GROUP  = "GROUP"

def _now_msk() -> datetime:
    return datetime.now(MSK)

def _get_successors(group_key: str, family_key: str) -> List[int]:
    """Преемники из таблицы family_successors или дефолтной карты."""
    # 1) Таблица
    with db_connection.get_connection().cursor() as cur:
        cur.execute("""
            select successors
              from family_successors
             where group_key=%s and family_key=%s
        """, (group_key, family_key))
        row = cur.fetchone()
    if row and row[0]:
        return list(row[0])

    # 2) Дефолтный конфиг
    key = (group_key, family_key)
    return list(config.FAMILY_SUCCESSOR_MAP_DEFAULT.get(key, []))

def _recent_recon_throttled(user_id: int, family_key: str, throttle_sec: int) -> bool:
    """
    Заглушка: если нужно - реализуй хранение последнего времени срабатывания
    (Redis/таблица). Пока всегда False, чтобы не блокировать.
    """
    return False

def _eligible_candidates_for_family(
    group_key: str,
    family_key: str,
    anchor: datetime,
    exclude_users: List[int],
) -> List[Dict[str, Any]]:
    """
    Кандидаты в этой же группе и текущем сегменте (в смене, не AFK/отпуск),
    с метриками профилей и нагрузок.
    """
    # Берём список людей "в смене" на момент сегмента. Небольшой хак:
    # +1 минута от anchor, чтобы точно попасть внутрь сегмента.
    in_shift = duty_repo.get_on_duty_members_now(group_key=group_key, now_local=anchor + timedelta(minutes=1))

    candidates: List[Dict[str, Any]] = []
    for u in in_shift:
        uid = u.get("user_id") if isinstance(u, dict) else u
        if uid in exclude_users:
            continue
        # Плановые отсутствия
        if duty_repo.is_user_absent_on(anchor.date(), uid):
            continue

        profile = users_repo.get_user_family_profile(uid)  # {"primary": str|None, "secondary": set[str]}
        L_total = duty_repo.get_user_total_load(uid)
        L_family = duty_repo.get_user_family_load(uid, family_key)
        rank = users_repo.get_member_rank(group_key, uid) if hasattr(users_repo, "get_member_rank") else None

        candidates.append({
            "user_id": uid,
            "primary": (profile.get("primary") == family_key),
            "secondary": (family_key in (profile.get("secondary") or set())),
            "L_total": float(L_total or 0.0),
            "L_family": float(L_family or 0.0),
            "rank": rank,
        })
    return candidates

def _sort_candidates_with_priorities(
    cand: List[Dict[str,Any]],
    rr_provider,
    target_rank: Optional[int],
    sticky_user_ids: List[int],
) -> List[Dict[str,Any]]:
    """Сортировка по приоритетам: stickiness → профиль → L_family → L_total → |rank-target| → rr."""
    rr_ptr = rr_provider() if rr_provider else 0

    def score(c):
        sticky = 0 if c["user_id"] in sticky_user_ids else 1
        prim   = 0 if c["primary"] else (1 if c["secondary"] else 2)
        load_f = c["L_family"]
        load_t = c["L_total"]
        tr = target_rank or c["rank"] or 99
        rk = c["rank"] or 99
        rank_diff = abs(rk - tr)
        return (sticky, prim, load_f, load_t, rank_diff, rr_ptr)

    return sorted(cand, key=score)

def _find_sticky_users_for_family(group_key: str, family_key: str, anchor: datetime) -> List[int]:
    """Кто уже держит это семейство в текущем сегменте (или держал ранее в сегменте)."""
    ass = duty_repo.get_family_assignments_in_segment(group_key, family_key, anchor)
    return list({a["user_id"] for a in ass})

def _assign_family_package(
    group_key: str,
    family_key: str,
    anchor: datetime,
    from_user: int,
    to_user: int
) -> Tuple[int,int]:
    """
    Передаём все задачи данного семейства from_user -> to_user в текущем сегменте.
    Возвращает (moved, skipped)
    """
    pkg = duty_repo.get_user_family_package_in_segment(group_key, family_key, from_user, anchor)
    if not pkg:
        return (0,0)

    moved, skipped = 0, 0
    for task in pkg:
        ok = duty_repo.reassign_single_task(task_id=task["assignment_id"], new_user_id=to_user)
        if ok: moved += 1
        else:  skipped += 1
    return (moved, skipped)

def recon_on_afk(
    user_id: int,
    group_key: str,
    now_local: Optional[datetime]=None,
    mode: Optional[str]=None
) -> Dict[str,Any]:
    """
    Запускает реконфигурацию по семействам, когда пользователь ушёл AFK.
    Возвращает counters: kept, reassigned, degraded, skipped, details[...]
    """
    now_local = now_local or _now_msk()
    mode = (mode or config.FAMILY_RECON_DEFAULT_MODE).upper()
    assert mode in (RECON_SOFT, RECON_FAMILY, RECON_GROUP)

    anchor = time_repo.anchor_for_datetime(now_local, group_key)

    families = duty_repo.get_families_of_user_in_segment(group_key, user_id, anchor)
    kept = 0
    reassigned = 0
    degraded = 0
    skipped = 0
    details: List[Dict[str, Any]] = []

    for family_key in families:
        # Throttle
        if _recent_recon_throttled(user_id, family_key, getattr(config, "FAMILY_RECON_THROTTLE_SEC", 180)):
            skipped += 1
            details.append({"family": family_key, "action": "skipped", "reason": "throttled"})
            continue

        # Кандидаты своей группы
        cand = _eligible_candidates_for_family(group_key, family_key, anchor, exclude_users=[user_id])
        sticky_ids = _find_sticky_users_for_family(group_key, family_key, anchor)
        target_rank = duty_repo.get_family_target_rank(family_key)

        cand = _sort_candidates_with_priorities(
            cand,
            rr_provider=duty_repo.get_rr_pointer,
            target_rank=target_rank,
            sticky_user_ids=sticky_ids
        )

        chosen: Optional[int] = cand[0]["user_id"] if cand else None
        if chosen is None:
            # Преемники из successor_map
            successors = _get_successors(group_key, family_key)
            successors = [u for u in successors if u != user_id]
            if successors:
                chosen = successors[0]

        if chosen is not None:
            moved, sk = _assign_family_package(group_key, family_key, anchor, from_user=user_id, to_user=chosen)
            reassigned += moved
            skipped    += sk
            details.append({"family": family_key, "action": "reassigned", "to": chosen, "moved": moved, "skipped": sk})
            continue

        # FAMILY-REPACK: перепак только внутри семейства в сегменте
        if mode in (RECON_FAMILY, RECON_GROUP):
            repacked = duty_repo.family_repack_in_group(group_key, family_key, anchor)
            if repacked > 0:
                reassigned += repacked
                details.append({"family": family_key, "action": "family_repack", "count": repacked})
                continue

        # GROUP-REPACK: крайний случай
        if mode == RECON_GROUP:
            repacked = duty_repo.group_repack_segment(group_key, anchor)
            if repacked > 0:
                reassigned += repacked
                details.append({"family": family_key, "action": "group_repack", "count": repacked})
                continue

        # Минимально жизнеспособный поднабор
        mvp, rest = duty_repo.split_family_package_mvp(group_key, family_key, user_id, anchor)
        took = 0
        if mvp:
            cand2 = _eligible_candidates_for_family(group_key, family_key, anchor, exclude_users=[user_id])
            cand2 = _sort_candidates_with_priorities(
                cand2,
                rr_provider=duty_repo.get_rr_pointer,
                target_rank=target_rank,
                sticky_user_ids=sticky_ids
            )
            if cand2:
                chosen2 = cand2[0]["user_id"]
                for task in mvp:
                    ok = duty_repo.reassign_single_task(task_id=task["assignment_id"], new_user_id=chosen2)
                    if ok: took += 1

        reassigned += took
        degraded  += len(rest) + (len(mvp) - took)
        details.append({"family": family_key, "action": "degraded", "took": took, "lost": len(rest) + (len(mvp) - took)})

    return {
        "kept": kept,
        "reassigned": reassigned,
        "degraded": degraded,
        "skipped": skipped,
        "details": details
    }
