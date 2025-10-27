# /home/telegrambot/shift_tracker_bot/database/rank_rotation_repository.py
# -*- coding: utf-8 -*-
from typing import Optional, Dict, Any
from datetime import date, timedelta
from .connection import db_connection
import logging

logger = logging.getLogger(__name__)

TABLE = "rank_rotation_rules"


def get_rule(group_key: str) -> Optional[Dict[str, Any]]:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(f"""
                SELECT mode, period_days, epoch, is_enabled
                FROM {TABLE}
                WHERE group_key=%s
            """, (group_key,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "mode": row[0],
                "period_days": int(row[1]),
                "epoch": row[2],
                "is_enabled": bool(row[3]),
            }
    except Exception:
        logger.exception("rank_rotation.get_rule failed group=%s", group_key)
        return None


def upsert_rule(group_key: str, period_days: int, epoch: date, enabled: bool = True,
                mode: str = "flip_1_2") -> bool:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(f"""
                INSERT INTO {TABLE} (group_key, mode, period_days, epoch, is_enabled)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (group_key) DO UPDATE
                  SET mode=EXCLUDED.mode,
                      period_days=EXCLUDED.period_days,
                      epoch=EXCLUDED.epoch,
                      is_enabled=EXCLUDED.is_enabled,
                      updated_at=NOW()
            """, (group_key, mode, int(period_days), epoch, bool(enabled)))
        db_connection.get_connection().commit()
        return True
    except Exception:
        db_connection.get_connection().rollback()
        logger.exception("rank_rotation.upsert_rule failed group=%s", group_key)
        return False


def set_enabled(group_key: str, enabled: bool) -> bool:
    try:
        with db_connection.get_connection().cursor() as cur:
            cur.execute(f"""
                UPDATE {TABLE}
                   SET is_enabled=%s, updated_at=NOW()
                 WHERE group_key=%s
            """, (bool(enabled), group_key))
        db_connection.get_connection().commit()
        return True
    except Exception:
        db_connection.get_connection().rollback()
        logger.exception("rank_rotation.set_enabled failed group=%s", group_key)
        return False


# =========================
# Runtime helpers (pure-Python, no writes)
# =========================

def _safe_int(x, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return int(default)


def _coerce_epoch(ep) -> Optional[date]:
    """
    Принимает date или 'YYYY-MM-DD' и возвращает date, иначе None.
    """
    if isinstance(ep, date):
        return ep
    try:
        from datetime import datetime as _dt
        return _dt.strptime(str(ep), "%Y-%m-%d").date()
    except Exception:
        return None


def compute_offset(epoch: date, period_days: int, on_date: date) -> int:
    """
    Смещение циклов относительно epoch: floor((on_date - epoch).days / period_days).
    Работает и для дат в прошлом (может вернуть отрицательное значение).
    """
    pd = max(1, _safe_int(period_days, 1))
    return (on_date - epoch).days // pd


def compute_next_rotation_date(epoch: date, period_days: int, ref_date: date) -> date:
    """
    Корректно вычисляет СЛЕДУЮЩУЮ дату ротации относительно ref_date.
    Если ref_date попадает точно на границу цикла (epoch + k*period),
    следующей считается граница СПУСТЯ один период (строго вперёд).
    """
    pd = max(1, _safe_int(period_days, 1))
    delta_days = (ref_date - epoch).days
    cycles = delta_days // pd
    return epoch + timedelta(days=(cycles + 1) * pd)


def get_next_rotation(group_key: str, ref_date: Optional[date] = None) -> Optional[date]:
    """
    Возвращает ближайшую будущую дату ротации (строго не в прошлом) по параметрам из БД.
    Если правило не найдено/выключено/некорректно — None.
    """
    r = get_rule(group_key)
    if not r or not r.get("is_enabled"):
        return None
    ep = _coerce_epoch(r.get("epoch"))
    pd = _safe_int(r.get("period_days"), 0)
    if not ep or pd <= 0:
        return None
    if ref_date is None:
        ref_date = date.today()
    return compute_next_rotation_date(ep, pd, ref_date)


def get_phase(group_key: str, on_date: Optional[date] = None) -> Optional[int]:
    """
    Возвращает фазу (1 или 2) режима flip_1_2 на указанную дату (по умолчанию — сегодня).
    Если правило недоступно — None.
    """
    r = get_rule(group_key)
    if not r or not r.get("is_enabled"):
        return None
    ep = _coerce_epoch(r.get("epoch"))
    pd = _safe_int(r.get("period_days"), 0)
    if not ep or pd <= 0:
        return None
    if on_date is None:
        on_date = date.today()
    off = compute_offset(ep, pd, on_date)
    # flip_1_2: 0-й, 2-й, 4-й... интервалы → фаза 1; 1-й, 3-й... → фаза 2
    return 1 if (off % 2) == 0 else 2
