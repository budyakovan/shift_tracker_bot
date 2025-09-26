# -*- coding: utf-8 -*-
# Telegram handlers for duty import/export (CSV without RACI; only base columns)
# python-telegram-bot v20+
import os
import csv
import io
from datetime import datetime
from typing import Dict

import psycopg2
import psycopg2.extras
from telegram import Update, InputFile
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

# ===== Авторизация (админ) =====
try:
    from utils.auth import require_admin
except ImportError:
    # fallback no-op decorator
    def require_admin(func):
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        return wrapper

# ===== Общие константы =====
WAITING_FILE = 1

BASE_COLS = ["key", "title", "weight", "office_required", "target_rank", "min_rank", "description"]

# ===== Подключение к БД через общий коннектор =====
def get_conn():
    """Берём соединение из database.connection.db_connection.
    Если модуль недоступен — используем DATABASE_URL/DB_DSN как фоллбэк.
    """
    try:
        from database.connection import db_connection
        conn = db_connection.get_connection()
        if conn is None or getattr(conn, "closed", 1) != 0:
            conn = db_connection.connect()
        if not getattr(conn, "autocommit", False):
            conn.autocommit = True
        return conn
    except Exception as e:
        dsn = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
        if not dsn:
            raise RuntimeError("Нет подключения через database.connection и не задано DATABASE_URL/DB_DSN") from e
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return conn

# ===== Бизнес-логика импорта/экспорта =====
def _coerce_int_or_none(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("none", "nan"):
        return None
    try:
        return int(float(s))
    except Exception:
        return None

def _coerce_bool(v):
    if v is None: return False
    s = str(v).strip().lower()
    return s in ("1", "true", "t", "yes", "y", "да", "истина")

def _upsert_duty(cur, row: Dict) -> int:
    weight = _coerce_int_or_none(row.get("weight")) or 10
    office_required = _coerce_bool(row.get("office_required"))
    target_rank = _coerce_int_or_none(row.get("target_rank"))
    min_rank = _coerce_int_or_none(row.get("min_rank"))
    description = (row.get("description") or "").strip()
    key = (row.get("key") or "").strip()
    title = (row.get("title") or "").strip()

    if not key or not title:
        raise ValueError("key/title не должны быть пустыми")

    cur.execute(
        """
        INSERT INTO duty (key, title, description, weight, office_required, target_rank, min_rank, is_active)
        VALUES (%(key)s, %(title)s, %(description)s, %(weight)s, %(office_required)s, %(target_rank)s, %(min_rank)s, TRUE)
        ON CONFLICT (key) DO UPDATE SET
          title = EXCLUDED.title,
          description = EXCLUDED.description,
          weight = EXCLUDED.weight,
          office_required = EXCLUDED.office_required,
          target_rank = COALESCE(EXCLUDED.target_rank, duty.target_rank),
          min_rank = COALESCE(EXCLUDED.min_rank, duty.min_rank),
          is_active = TRUE
        RETURNING id;
        """,
        {
            "key": key,
            "title": title,
            "description": description,
            "weight": weight,
            "office_required": office_required,
            "target_rank": target_rank,
            "min_rank": min_rank,
        },
    )
    duty_id = cur.fetchone()[0]
    return duty_id

def import_csv_bytes(data: bytes) -> Dict[str,int]:
    """Парсим CSV (только базовые колонки) и импортируем. Возвращаем статистику."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    if "key" not in reader.fieldnames or "title" not in reader.fieldnames:
        raise ValueError("CSV должен содержать как минимум колонки: key,title")

    cnt_duties = 0
    conn = get_conn()
    with conn.cursor() as cur:
        for row in reader:
            base_row = {k: row.get(k) for k in BASE_COLS}
            _upsert_duty(cur, base_row)
            cnt_duties += 1
        try:
            if not getattr(conn, "autocommit", False):
                conn.commit()
        except Exception:
            pass
    return {"duties": cnt_duties}

def export_to_csv_bytes() -> bytes:
    """Экспорт duty в CSV (только базовые колонки)."""
    header = BASE_COLS
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            """
            SELECT key, title, weight, office_required, target_rank, min_rank, description
            FROM duty
            WHERE is_active = TRUE
            ORDER BY key
            """
        )
        duties = cur.fetchall()

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header)
    writer.writeheader()
    for d in duties:
        writer.writerow({
            "key": d["key"],
            "title": d["title"],
            "weight": d["weight"],
            "office_required": int(bool(d["office_required"])),
            "target_rank": d["target_rank"] if d["target_rank"] is not None else "",
            "min_rank": d["min_rank"] if d["min_rank"] is not None else "",
            "description": d["description"] or "",
        })
    return out.getvalue().encode("utf-8")

# ===== Telegram Handlers =====
@require_admin
async def duty_import_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Загрузи CSV-файл с каталогом обязанностей (без RACI).\\n"
        "Минимальные колонки: key,title. Опционально: weight,office_required,target_rank,min_rank,description.\\n"
        "Отправь файл в ответ на это сообщение."
    )
    ctx.user_data["awaiting_duty_import"] = True
    return WAITING_FILE

@require_admin
async def duty_import_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_duty_import"):
        return ConversationHandler.END

    doc = update.message.document
    if not doc or not (doc.file_name.endswith(".csv")):
        await update.message.reply_text("Нужен .csv файл. Попробуй снова /duty_import.")
        return ConversationHandler.END

    tgfile = await doc.get_file()
    file_bytes = await tgfile.download_as_bytearray()
    try:
        stats = import_csv_bytes(bytes(file_bytes))
    except Exception as e:
        await update.message.reply_text(f"❌ Импорт не удался: {e}")
        return ConversationHandler.END

    await update.message.reply_text(f"✅ Импорт завершён: {stats['duties']} обязанностей.")
    ctx.user_data["awaiting_duty_import"] = False
    return ConversationHandler.END

@require_admin
async def duty_export_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = export_to_csv_bytes()
    fname = f"duty_catalog_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await update.message.reply_document(document=InputFile(io.BytesIO(data), filename=fname),
                                        caption="Экспорт каталога обязанностей (без RACI).")

def register_import_export_handlers(app):
    conv = ConversationHandler(
        entry_points=[CommandHandler("duty_import", duty_import_cmd)],
        states={
            WAITING_FILE: [MessageHandler(filters.Document.ALL, duty_import_file)],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("duty_export", duty_export_cmd))
