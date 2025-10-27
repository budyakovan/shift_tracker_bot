# /home/telegrambot/shift_tracker_bot/main.py
# -*- coding: utf-8 -*-
import logging
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

from config import config

from handlers.start import start_command
from handlers.common import handle_message, my_id_command
from handlers.duty_handlers import (
    assign_duties,       # /assign_duties [YYYY-MM-DD] [group_key]
    my_duties,           # /my_duties [дата]
    my_duties_next,      # /my_duties_next
    duties_now,          # /duties_now [group_key]
    duties_all,          # /duties_all [YYYY-MM-DD] [group_key]
)

from handlers.duty_admin_handlers import (
    rank_set, rank_list,
    duty_exclude, duty_exclude_del,
    assign_duties_rr,     # /assign_duties_rr [YYYY-MM-DD] [group_key]
    assign_duties_now,    # /assign_duties_now [group_key]
    who_on_shift_now,     # /who_on_shift_now [group_key]
    who_on_shift_now_debug, # /who_on_shift_now_debug [group_key]
    # админская версия вывода «сейчас»
)


from handlers.help_handlers import (
    help_command,
    help_users_command,
    help_groups_command,
    help_full_command,
    help_users_short_command,
    help_groups_short_command,
    help_time_profiles_command,
    help_time_profiles_short_command,
    help_vacations_command,          # NEW
    help_vacations_short_command,    # NEW
    help_sick_command,               # NEW
    help_sick_short_command,         # NEW
    help_duties_command,
    help_duties_short_command,
    help_location_command,
    help_location_short_command,
    help_rank_rotation_command,
    help_rank_rotation_short_command,
    help_rank_command,               # NEW
    help_rank_short_command,         # NEW
    help_holidays_command,
    help_holidays_short_command,
)

from handlers.holiday_handlers import holidays_status, holidays_sync

from handlers.schedule_handlers import (
    today_command,
    tomorrow_command,
    next_command,
    my_next_command,
    ondate_command,
)

from handlers.users_handlers import (
    admin_removeuser,
    admin_update_all_users,
    admin_users,
    admin_pending,
    admin_approve,
    admin_promote,
    admin_demote,
)

import handlers.absence_handlers as absence_handlers



from handlers.rank_rotation_handlers import (
    admin_rank_rotation_set,
    admin_rank_rotation_show,
    admin_rank_rotation_off,
    pair_stats_command,
    admin_rank_rotation_now,
    admin_rank_rotation_diag,
    admin_rank_rotation_apply,
)

from handlers.location_handlers import (
    loc_assign,
    loc_report,
    loc_clear_future,
    loc_next,
    loc_assign_manual,
    loc_probe,
    loc_probe_exec,
)

from handlers.notif_handlers import (
    admin_notif_set,
    admin_notif_show,
    admin_notif_list,
    admin_notif_clear,
    admin_notif_ping,
)

from tools.duty_import_export_handlers import register_import_export_handlers
from handlers.duty_catalog import duties_catalog, duty_show
import handlers.time_handlers as time_handlers

from handlers.afk_handlers import cmd_afk, cmd_back, cmd_afk_list, on_work_topic_message


# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG для удобной диагностики интеграции notif_endpoints
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# Универсальный обработчик ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    import json
    err = context.error

    # Полный стек
    logging.error("Unhandled exception", exc_info=(type(err), err, err.__traceback__))

    # Доп. контекст апдейта
    try:
        upd_repr = None
        if update:
            if hasattr(update, "to_dict"):
                upd_repr = json.dumps(update.to_dict(), ensure_ascii=False, default=str)[:4000]
            else:
                upd_repr = str(update)[:4000]
        logging.debug("Update context: %s", upd_repr)
        logging.debug("Exception repr: %r", err)
    except Exception:
        pass

    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ Произошла ошибка. Логи сохранены, разберёмся.")
    except Exception:
        pass



def setup_handlers(application: Application):
    """Настройка обработчиков команд"""

    # Клавиатура
    application.add_handler(MessageHandler(filters.Regex('^🏢 Локации$'), loc_next))
    application.add_handler(MessageHandler(filters.Regex('^📅 График$'), next_command))

    # Импорт/экспорт каталога обязанностей
    register_import_export_handlers(application)

    # Каталог обязанностей
    application.add_handler(CommandHandler("duties_catalog", duties_catalog))
    application.add_handler(CommandHandler("duty_show", duty_show))
    application.add_handler(CommandHandler("help_duties", help_duties_command))
    application.add_handler(CommandHandler("help_duties_short", help_duties_short_command))

    # === Справка ===
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("help_full", help_full_command))
    application.add_handler(CommandHandler("help_users", help_users_command))
    application.add_handler(CommandHandler("help_users_short", help_users_short_command))
    application.add_handler(CommandHandler("help_groups", help_groups_command))
    application.add_handler(CommandHandler("help_groups_short", help_groups_short_command))
    application.add_handler(CommandHandler("help_time_profiles", help_time_profiles_command))
    application.add_handler(CommandHandler("help_time_profiles_short", help_time_profiles_short_command))  # опц.
    application.add_handler(CommandHandler("help_vacations", help_vacations_command))  # NEW
    application.add_handler(CommandHandler("help_vacations_short", help_vacations_short_command))  # NEW
    application.add_handler(CommandHandler("help_sick", help_sick_command))  # NEW
    application.add_handler(CommandHandler("help_sick_short", help_sick_short_command))  # NEW
    application.add_handler(CommandHandler("help_location", help_location_command))
    application.add_handler(CommandHandler("help_location_short", help_location_short_command))
    application.add_handler(CommandHandler("help_rank_rotation", help_rank_rotation_command))
    application.add_handler(CommandHandler("help_rank_rotation_short", help_rank_rotation_short_command))
    application.add_handler(CommandHandler("help_rank", help_rank_command))               # NEW
    application.add_handler(CommandHandler("help_rank_short", help_rank_short_command))   # NEW
    application.add_handler(CommandHandler("help_holidays", help_holidays_command))
    application.add_handler(CommandHandler("help_holidays_short", help_holidays_short_command))

    # === Основные команды ===
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("id", my_id_command))
    application.add_handler(CommandHandler("ondate", ondate_command))
    application.add_handler(CommandHandler("next", next_command))
    application.add_handler(CommandHandler("my_next", my_next_command))

    # === Пользователи, админ ===
    application.add_handler(CommandHandler("admin_removeuser", admin_removeuser))
    application.add_handler(CommandHandler("admin_update_all_users", admin_update_all_users))
    application.add_handler(CommandHandler("admin_users", admin_users))
    application.add_handler(CommandHandler("admin_pending", admin_pending))
    application.add_handler(CommandHandler("admin_approve", admin_approve))
    application.add_handler(CommandHandler("admin_promote", admin_promote))
    application.add_handler(CommandHandler("admin_demote", admin_demote))

    # === Тайм-группы (новые) ===
    application.add_handler(CommandHandler("admin_time_groups_create", time_handlers.admin_time_groups_create))
    application.add_handler(CommandHandler("admin_time_groups_add_user", time_handlers.admin_time_groups_add_user))
    application.add_handler(CommandHandler("admin_time_groups_remove_user", time_handlers.admin_time_groups_remove_user))
    application.add_handler(CommandHandler("admin_time_groups_set_pos", time_handlers.admin_time_groups_set_pos))
    application.add_handler(CommandHandler("admin_time_groups_show", time_handlers.admin_time_groups_show))
    application.add_handler(CommandHandler("admin_time_groups_set_period", time_handlers.admin_time_groups_set_period))
    application.add_handler(CommandHandler("admin_time_groups_list", time_handlers.admin_time_groups_list))
    application.add_handler(CommandHandler("admin_time_profile_list", time_handlers.admin_time_profile_list))
    application.add_handler(CommandHandler("admin_time_profile_create", time_handlers.admin_time_profile_create))
    application.add_handler(CommandHandler("admin_time_profile_add_slot", time_handlers.admin_time_profile_add_slot))
    application.add_handler(CommandHandler("admin_time_profile_clear_slots", time_handlers.admin_time_profile_clear_slots))
    application.add_handler(CommandHandler("admin_time_profile_show", time_handlers.admin_time_profile_show))
    application.add_handler(CommandHandler("admin_debug_date", time_handlers.admin_debug_date))
    application.add_handler(CommandHandler("admin_time_groups_delete", time_handlers.admin_time_groups_delete))
    application.add_handler(CommandHandler("admin_time_profile_delete", time_handlers.admin_time_profile_delete))

    # === Отпуск и больничный ===
    application.add_handler(CommandHandler("vacation_add", absence_handlers.vacation_add))
    application.add_handler(CommandHandler("vacation_list", absence_handlers.vacation_list))
    application.add_handler(CommandHandler("vacation_edit", absence_handlers.vacation_edit))
    application.add_handler(CommandHandler("vacation_del", absence_handlers.vacation_del))
    application.add_handler(CommandHandler("admin_vacation_add", absence_handlers.admin_vacation_add))
    application.add_handler(CommandHandler("admin_vacation_edit", absence_handlers.admin_vacation_edit))
    application.add_handler(CommandHandler("admin_vacation_del", absence_handlers.admin_vacation_del))
    application.add_handler(CommandHandler("sick_add", absence_handlers.sick_add))
    application.add_handler(CommandHandler("sick_list", absence_handlers.sick_list))
    application.add_handler(CommandHandler("sick_edit", absence_handlers.sick_edit))
    application.add_handler(CommandHandler("sick_del", absence_handlers.sick_del))
    application.add_handler(CommandHandler("admin_sick_add", absence_handlers.admin_sick_add))
    application.add_handler(CommandHandler("admin_sick_edit", absence_handlers.admin_sick_edit))
    application.add_handler(CommandHandler("admin_sick_del", absence_handlers.admin_sick_del))

    # агрегированные отчёты (админ)
    application.add_handler(CommandHandler("vacations_all", absence_handlers.vacations_all))
    application.add_handler(CommandHandler("sick_all", absence_handlers.sick_all))

    # === Локации ===
    application.add_handler(CommandHandler("loc_assign", loc_assign))
    application.add_handler(CommandHandler("loc_report", loc_report))
    application.add_handler(CommandHandler("loc_clear_future", loc_clear_future))
    application.add_handler(CommandHandler("loc_next", loc_next))
    application.add_handler(CommandHandler("loc_probe", loc_probe))  # NEW
    application.add_handler(CommandHandler("loc_assign_manual", loc_assign_manual))  # NEW
    application.add_handler(CommandHandler("loc_probe_exec", loc_probe_exec))


    # === Ротации ===
    application.add_handler(CommandHandler("admin_rank_rotation_now", admin_rank_rotation_now))
    application.add_handler(CommandHandler("admin_rank_rotation_set", admin_rank_rotation_set))
    application.add_handler(CommandHandler("admin_rank_rotation_show", admin_rank_rotation_show))
    application.add_handler(CommandHandler("admin_rank_rotation_off", admin_rank_rotation_off))
    application.add_handler(CommandHandler("pair_stats", pair_stats_command))
    application.add_handler(CommandHandler("admin_rank_rotation_diag", admin_rank_rotation_diag))  # NEW
    application.add_handler(CommandHandler("admin_rank_rotation_apply", admin_rank_rotation_apply))  # NEW

    # === Календарь РФ (праздники/переносы) ===
    application.add_handler(CommandHandler("holidays_status", holidays_status))
    application.add_handler(CommandHandler("holidays_sync", holidays_sync))

    # === AFK-команды ===
    application.add_handler(CommandHandler("afk", cmd_afk))
    application.add_handler(CommandHandler("back", cmd_back))
    application.add_handler(CommandHandler("afk_list", cmd_afk_list))

    # === Уведомления, оповещения ===
    application.add_handler(CommandHandler("admin_notif_set", admin_notif_set))
    application.add_handler(CommandHandler("admin_notif_show", admin_notif_show))
    application.add_handler(CommandHandler("admin_notif_list", admin_notif_list))
    application.add_handler(CommandHandler("admin_notif_clear", admin_notif_clear))
    application.add_handler(CommandHandler("admin_notif_ping", admin_notif_ping))

    # === Пользовательские ===
    application.add_handler(CommandHandler("my_duties", my_duties))
    application.add_handler(CommandHandler("my_duties_next", my_duties_next))
    application.add_handler(CommandHandler("duties_now", duties_now))
    application.add_handler(CommandHandler("duties_all", duties_all))

    # === Админские ===
    application.add_handler(CommandHandler("assign_duties", assign_duties))
    application.add_handler(CommandHandler("assign_duties_rr", assign_duties_rr))
    application.add_handler(CommandHandler("assign_duties_now", assign_duties_now))
    application.add_handler(CommandHandler("rank_set", rank_set))
    application.add_handler(CommandHandler("rank_list", rank_list))
    application.add_handler(CommandHandler("duty_exclude", duty_exclude))
    application.add_handler(CommandHandler("duty_exclude_del", duty_exclude_del))
    application.add_handler(CommandHandler("who_on_shift_now", who_on_shift_now))
    application.add_handler(CommandHandler("who_on_shift_now_debug", who_on_shift_now_debug))
    # опц.: отдельный вывод «сейчас» для админов
    # application.add_handler(CommandHandler("duties_now_admin", duties_now_admin))


    # ===== Слушатель сообщений в форумных темах супергрупп =====
    # Внутри on_work_topic_message сопоставляем чат+тему с notif_endpoints.
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.SUPERGROUP
            & filters.IS_TOPIC_MESSAGE,
            on_work_topic_message,
        ),
        group=0,  # чтобы этот хендлер сработал раньше общего текстового
    )

    # === Обработчики ошибок и неизвестных команд ===
    application.add_error_handler(error_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=1)


def main():
    """Точка входа"""
    application = Application.builder().token(config.BOT_TOKEN).build()
    setup_handlers(application)
    logger.info("🚀 Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
