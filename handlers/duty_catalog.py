# /home/telegrambot/shift_tracker_bot/handlers/duty_catalog.py
# -*- coding: utf-8 -*-
# Handlers to view the duty catalog (without RACI)
from telegram import Update
from telegram.ext import ContextTypes
from database.duty_catalog_repository import fetch_catalog, get_by_key

OFFICE_EMOJI = {True: "🏢", False: "🏠"}

def _rank_span(min_rank, target_rank):
    def as_txt(x): return "—" if x is None else str(x)
    return f"{as_txt(min_rank)}…{as_txt(target_rank)}"

def _chunk_lines(lines, max_len=3800):
    chunks, buf_len, buf = [], 0, []
    for ln in lines:
        L = len(ln) + 1
        if buf_len + L > max_len and buf:
            chunks.append("\n".join(buf)); buf, buf_len = [], 0
        buf.append(ln); buf_len += L
    if buf:
        chunks.append("\n".join(buf))
    return chunks

async def duties_catalog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args).strip() if ctx.args else ""
    rows = fetch_catalog(search=q or None, limit=500)

    if not rows:
        await update.message.reply_text("Каталог пуст. Загрузите CSV через /duty_import.")
        return

    header = "📚 <b>Каталог обязанностей</b>" + (f" (фильтр: <i>{q}</i>)" if q else "")
    lines = [header]
    for r in rows:
        office = OFFICE_EMOJI[bool(r["office_required"])]
        ranks = _rank_span(r["min_rank"], r["target_rank"])
        desc = (r["description"] or "").strip()
        if len(desc) > 120: desc = desc[:117] + "…"
        lines.append(
            f"• <code>{r['key']}</code> — <b>{r['title']}</b>  "
            f"[w={r['weight']}, {office}, rank {ranks}]"
            + (f"\n  <i>{desc}</i>" if desc else "")
        )

    for chunk in _chunk_lines(lines):
        await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)

async def duty_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /duty_show <key>")
        return
    key = ctx.args[0]
    r = get_by_key(key)
    if not r:
        await update.message.reply_text("Не нашёл такую обязанность по key.")
        return

    office = OFFICE_EMOJI[bool(r["office_required"])]
    ranks = _rank_span(r["min_rank"], r["target_rank"])
    text = (
        f"🔎 <b>{r['title']}</b>\n"
        f"key: <code>{r['key']}</code>\n"
        f"Вес: <b>{r['weight']}</b>\n"
        f"Офис: {office}\n"
        f"Ранги: {ranks}\n"
        f"Создано: {r['created_at']:%Y-%m-%d}\n"
        f"\n{(r['description'] or '').strip()}"
    )
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
