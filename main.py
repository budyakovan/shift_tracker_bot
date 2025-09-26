import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

from config import config

from handlers.start import start_command
from handlers.common import handle_message, my_id_command
from handlers.help_handlers import (
    help_command,
    help_users_command,
    help_groups_command,
    help_admin_all_command,
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

)



from handlers.schedule_handlers import today_command, tomorrow_command, next_command, my_next_command, ondate_command

from handlers.admin_handlers import (
    admin_approve, admin_pending, admin_promote, admin_demote,
    admin_users, update_all_users, admin_help, remove_user,
    admin_groups, admin_group_create, admin_group_rename,
    admin_group_set_offset, admin_group_set_epoch, admin_group_delete,
    admin_set_group, admin_unset_group, admin_list_group,
)

import handlers.absence_handlers as absence_handlers

from handlers.duty_handlers import (
    duty_add, duties_list, duty_update, duty_delete,
    assign_duties, duties_today, my_duties, my_duties_next,
)

from handlers.duty_admin_handlers import (
    rank_set, rank_list,
    duty_exclude, duty_exclude_del, duty_exclude_list,
    assign_duties_rr
)

from handlers.location_handlers import loc_assign, loc_today, loc_report
from tools.duty_import_export_handlers import register_import_export_handlers
from handlers.duty_catalog import duties_catalog, duty_show
import handlers.time_handlers as time_handlers

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, config.LOG_LEVEL)
)
logger = logging.getLogger(__name__)


# Универсальный обработчик ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    import traceback
    logging.error("Unhandled exception", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ Произошла ошибка. Логи сохранены, разберёмся."
            )
    except Exception:
        pass


# Ответ на неизвестные команды
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤷 Не знаю такую команду. Посмотри /help")


def setup_handlers(application):
    """Настройка обработчиков команд"""

    # Регистрируем оба хендлера разом (/duty_import и /duty_export)
    register_import_export_handlers(application)

    # Каталог обязаностей
    application.add_handler(CommandHandler("duties_catalog", duties_catalog))
    application.add_handler(CommandHandler("duty_show", duty_show))
    application.add_handler(CommandHandler("help_duties", help_duties_command))
    application.add_handler(CommandHandler("help_duties_short", help_duties_short_command))
    application.add_handler(CommandHandler("my_duties_next", my_duties_next))

    # === Справка ===
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("help_full", help_full_command))
    application.add_handler(CommandHandler("help_users", help_users_command))
    application.add_handler(CommandHandler("help_users_short", help_users_short_command))
    application.add_handler(CommandHandler("help_groups", help_groups_command))
    application.add_handler(CommandHandler("help_groups_short", help_groups_short_command))
    application.add_handler(CommandHandler("help_time_profiles", help_time_profiles_command))
    application.add_handler(CommandHandler("help_time_profiles_short", help_time_profiles_short_command))  # опц.
    application.add_handler(CommandHandler("help_admin_all", help_admin_all_command))
    application.add_handler(CommandHandler("help_vacations", help_vacations_command))  # NEW
    application.add_handler(CommandHandler("help_vacations_short", help_vacations_short_command))  # NEW
    application.add_handler(CommandHandler("help_sick", help_sick_command))  # NEW
    application.add_handler(CommandHandler("help_sick_short", help_sick_short_command))  # NEW
    application.add_handler(CommandHandler("admin_help", admin_help))

    # === Основные команды ===
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("id", my_id_command))
    application.add_handler(CommandHandler("ondate", ondate_command))
    application.add_handler(CommandHandler("next", next_command))
    application.add_handler(CommandHandler("my_next", my_next_command))

    # === Пользователи, админ ===
    application.add_handler(CommandHandler("admin_approve", admin_approve))
    application.add_handler(CommandHandler("admin_pending", admin_pending))
    application.add_handler(CommandHandler("admin_promote", admin_promote))
    application.add_handler(CommandHandler("admin_demote", admin_demote))
    application.add_handler(CommandHandler("admin_users", admin_users))
    application.add_handler(CommandHandler("admin_removeuser", remove_user))
    application.add_handler(CommandHandler("admin_update_all_users", update_all_users))

    # === Группы смен (legacy duty groups) ===
    application.add_handler(CommandHandler("admin_groups", admin_groups))
    application.add_handler(CommandHandler("admin_group_create", admin_group_create))
    application.add_handler(CommandHandler("admin_group_rename", admin_group_rename))
    application.add_handler(CommandHandler("admin_group_set_offset", admin_group_set_offset))
    application.add_handler(CommandHandler("admin_group_set_epoch", admin_group_set_epoch))
    application.add_handler(CommandHandler("admin_group_delete", admin_group_delete))
    application.add_handler(CommandHandler("admin_set_group", admin_set_group))
    application.add_handler(CommandHandler("admin_unset_group", admin_unset_group))
    application.add_handler(CommandHandler("admin_list_group", admin_list_group))

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
    application.add_handler(CommandHandler("admin_time_groups_set_tz", time_handlers.admin_time_groups_set_tz))

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


    # === Дежурства ===
    application.add_handler(CommandHandler("duty_add", duty_add))
    application.add_handler(CommandHandler("duties_list", duties_list))
    application.add_handler(CommandHandler("duty_update", duty_update))
    application.add_handler(CommandHandler("duty_delete", duty_delete))
    application.add_handler(CommandHandler("assign_duties", assign_duties))
    application.add_handler(CommandHandler("duties_today", duties_today))
    application.add_handler(CommandHandler("my_duties", my_duties))
    application.add_handler(CommandHandler("rank_set", rank_set))
    application.add_handler(CommandHandler("rank_list", rank_list))
    application.add_handler(CommandHandler("duty_exclude", duty_exclude))
    application.add_handler(CommandHandler("duty_exclude_del", duty_exclude_del))
    application.add_handler(CommandHandler("duty_exclude_list", duty_exclude_list))
    application.add_handler(CommandHandler("assign_duties_rr", assign_duties_rr))

    # === Локации ===
    application.add_handler(CommandHandler("loc_assign", loc_assign))
    application.add_handler(CommandHandler("loc_today", loc_today))
    application.add_handler(CommandHandler("loc_report", loc_report))

    # === Обработчики ошибок и неизвестных команд ===
    application.add_error_handler(error_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))


def main():
    """Точка входа"""
    application = Application.builder().token(config.BOT_TOKEN).build()
    setup_handlers(application)
    logger.info("🚀 Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
