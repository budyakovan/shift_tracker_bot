# /home/telegrambot/shift_tracker_bot/handlers/help_texts.py
# -*- coding: utf-8 -*-
"""
Все тексты справок (HTML).
Правила форматирования:
- Команды без аргументов — plain (/today).
- Команды с аргументами — <code>/cmd</code> <i>arg</i> ...
- Заголовки — <b>...</b>
"""

HELP_MAIN_FULL = """
❓ <b>Полная справка</b>

👋 Повседневное:
➤ /today — смены на сегодня
➤ /tomorrow — смены на завтра
➤ <code>/ondate</code> <i>DD.MM[.YYYY]</i> — кто дежурит в указанную дату

👥 Пользователи:
➤ /admin_pending — список ожидающих
➤ <code>/admin_approve</code> <i>user_id</i> [<i>group_key</i>] — одобрить
➤ /admin_users — все пользователи
➤ <code>/admin_removeuser</code> <i>user_id</i> — удалить
➤ <code>/admin_set_group</code> <i>user_id</i> <i>group_key</i> — назначить группу
➤ <code>/admin_unset_group</code> <i>user_id</i> — снять группу
➤ <code>/admin_list_group</code> <i>group_key</i> — пользователи в группе
➤ /admin_update_all_users — обновить профили (username/имена)

👷 Группы (тайм-группы):
➤ /admin_time_groups_list — список групп
➤ <code>/admin_time_groups_show</code> <i>group_key</i> — подробности по группе
➤ <code>/admin_time_groups_create</code> <i>group_key</i> <i>profile_key</i> <i>YYYY-MM-DD</i> <i>period</i> — создать/обновить
➤ <code>/admin_time_groups_add_user</code> <i>group_key</i> <i>user_id</i> <i>pos</i> — добавить пользователя
➤ <code>/admin_time_groups_remove_user</code> <i>group_key</i> <i>user_id</i> — удалить пользователя
➤ <code>/admin_time_groups_set_pos</code> <i>group_key</i> <i>user_id</i> <i>pos</i> — изменить позицию
➤ <code>/admin_time_groups_set_period</code> <i>group_key</i> <i>days</i> — период ротации
➤ <code>/admin_time_groups_delete</code> <i>group_key</i> — удалить группу

⏱ Тайм-профили:
➤ /admin_time_profile_list — список профилей
➤ <code>/admin_time_profile_create</code> <i>key</i> <i>description</i> — создать профиль
➤ <code>/admin_time_profile_add_slot</code> <i>key</i> <i>start</i> <i>end</i> — добавить слот (например 09:00 18:00)
➤ <code>/admin_time_profile_clear_slots</code> <i>key</i> — очистить слоты
➤ <code>/admin_time_profile_show</code> <i>key</i> — показать детали
➤ <code>/admin_time_profile_delete</code> <i>key</i> — удалить профиль

🏖 Отпуска:
➤ /vacation_add — добавить отпуск (бот спросит даты)
➤ /vacation_list — мои отпуска
➤ /vacation_edit — изменить отпуск
➤ /vacation_del — удалить отпуск
➤ /admin_vacation_add — добавить отпуск пользователю (админ)
➤ /admin_vacation_edit — изменить отпуск пользователя (админ)
➤ /admin_vacation_del — удалить отпуск пользователя (админ)

🤒 Больничные:
➤ /sick_add — добавить больничный (бот спросит даты)
➤ /sick_list — мои больничные
➤ /sick_edit — изменить больничный
➤ /sick_del — удалить больничный
➤ /admin_sick_add — добавить больничный пользователю (админ)
➤ /admin_sick_edit — изменить больничный пользователя (админ)
➤ /admin_sick_del — удалить больничный пользователя (админ)

🏢 Локации (офис/дом):
➤ <code>/loc_next</code> [<i>N</i>] [<i>group_key</i>] | <i>YYYY-MM-DD</i> [<i>YYYY-MM-DD</i>] [<i>group_key</i>] — план на период (до 30 дн. в сообщении)
➤ <code>/loc_assign</code> [<i>N</i>] [<i>group_key</i>] | <i>YYYY-MM-DD</i> [<i>N</i>] [<i>group_key</i>] | <i>YYYY-MM-DD</i> <i>YYYY-MM-DD</i> [<i>group_key</i>] — <b>админ</b>: назначить локации
➤ <code>/loc_report</code> <i>group_key</i> <i>date_from</i> <i>date_to</i> | <i>group_key</i> <i>YYYY-MM</i> — отчёт по офис-дням  
   └ Понимает «конец месяца»: например <code>2025-11-31 → 2025-11-30</code>.
➤ <code>/loc_clear_future</code> [<i>group_key</i>] — удалить будущие назначения
➤ /help_location — подробная справка по правилам (🔷/🔶, ночи/выходные, фолбэки)

🔁 Ротации пар/рангов:
➤ <code>/admin_rank_rotation_set</code> <i>group_key</i> <i>period_days</i> <i>YYYY-MM-DD</i> [on] — задать эпоху/период (и включить)
➤ <code>/admin_rank_rotation_show</code> <i>group_key</i> — показать текущее правило
➤ <code>/admin_rank_rotation_off</code> <i>group_key</i> [on|off] — включить/выключить
➤ /help_rank_rotation — справка по ротации

📅 Праздники/выходные:
➤ /holidays_status — показать источник и покрытие календаря
➤ <code>/holidays_sync</code> <i>YYYY</i>|<i>YYYY-YYYY</i> — <b>админ</b>: синхронизировать календарь  
   (заполняет <code>ru_calendar</code> по <code>ru_is_holiday_mv</code>)
➤ /help_holidays — подробная справка по календарю
""".strip()
HELP_MAIN_SHORT = """
❓ <b>Справка — основные команды</b>

👋 <b>Повседневное</b>
➤ /today — смены на сегодня
➤ /tomorrow — смены на завтра
➤ <code>/ondate</code> <i>DD.MM[.YYYY]</i> — кто дежурит в указанную дату

⚙️ <b>Конфигурация</b>
➤ /admin_users — список пользователей
➤ /admin_time_groups_list — список групп
➤ /admin_time_profile_list — список профилей
➤ /vacations_all [<i>период</i>] — все отпуска
➤ /sick_all [<i>период</i>] — все больничные (админ)

📚 <b>Справка по разделам</b>
➤ /help_groups — группы (админ)
➤ /help_vacations — отпуска
➤ /help_sick — больничные
➤ /help_duties — обязанности
➤ /help_location — локации
➤ /help_rank_rotation_short — ротация по рангам (парные СП+С)
➤ /help_rank_short — ранги
➤ /help_holidays_short — праздники/календарь
""".strip()
HELP_USERS_SHORT = """
<b>Доступные команды:</b>
➡️ /help_users — полная справка
➡️ /admin_pending — ожидающие авторизации
➡️ /admin_time_groups_list — список тайм-групп
️️➡️ /admin_time_profile_list — список профилей времени
➤ <code>/admin_approve</code> <i>user_id</i> — авторизовать пользователя
➤ <code>/admin_removeuser</code> <i>user_id</i> — удалить пользователя
➤ <code>/admin_promote</code> <i>user_id</i> — сделать пользователя админом
➤ <code>/admin_demote</code> <i>user_id</i> — удалить права админа
""".strip()
HELP_USERS_FULL = """
👥 <b>Работа с пользователями</b>

📋 <b>Просмотр</b>
➡️ /admin_users — полный список пользователей (ожидающие + зарегистрированные)
➡️ /admin_pending — только ожидающие одобрения пользователи
➤ <code>/admin_list_group</code> <i>group_key</i> — пользователи в конкретной группе

✅ <b>Одобрение и удаление</b>
➤ <code>/admin_approve</code> <i>user_id</i> [group_key] — одобрить пользователя (опционально назначить группу)
➤ <code>/admin_removeuser</code> <i>user_id</i> — полностью удалить пользователя из системы

👑 <b>Админ-права</b>
➤ <code>/admin_promote</code> <i>user_id</i> — назначить администратором
➤ <code>/admin_demote</code> <i>user_id</i> — снять права администратора

🔄 <b>Служебные команды</b>
➤ /admin_update_all_users — обновить профили пользователей (usernames и имена из Telegram)

📝 <b>Формат вывода</b>
• 🔸 — администратор 
• 🔹 — пользователь 
• ❔ — ожидающий одобрения
• ID пользователей отображаются в <code>моноширинном формате</code> для удобного копирования

💡 <b>Примеры использования</b>
<code>/admin_approve 123456789</code> — одобрить пользователя с ID 123456789
<code>/admin_approve 123456789 group_a</code> — одобрить и назначить группу "group_a"
<code>/admin_promote 987654321</code> — сделать пользователя администратором
""".strip()
HELP_GROUPS_FULL = """
👷 <b>Тайм-группы (админ)</b>

<b>Что это:</b>
Тайм-группа — это ротационная группа пользователей с общей «эпохой» (стартовой датой), 
периодом ротации (в днях) и часовым поясом. 
Используется для автоматического определения текущей/следующей смены по позиции участника.

<b>Доступ:</b> команды ниже доступны только администраторам (нужен декоратор <code>@require_admin</code>).

───────────────────────

<b>Базовые команды</b>
➤ <code>/admin_time_groups_list</code> — список групп (кратко).
➤ <code>/admin_time_groups_show</code> <i>group_key</i> — подробности по группе.

<b>Создание и настройки</b>
➤ <code>/admin_time_groups_create</code> <i>group_key profile_key YYYY-MM-DD period</i> — создать/обновить группу.
   ├ <b>group_key</b> — ключ (например, <code>group_budyakov</code>)  
   ├ <b>profile_key</b> — связанный профиль (например, <code>team_budyakov</code>)  
   ├ <b>YYYY-MM-DD</b> — дата эпохи (например, <code>2025-09-05</code>)  
   └ <b>period</b> — период ротации в днях (например, <code>8</code>)  

➤ <code>/admin_time_groups_set_period</code> <i>group_key days</i> — сменить период.  

<b>Участники</b>
➤ <code>/admin_time_groups_add_user</code> <i>group_key user_id pos</i> — добавить пользователя.  
➤ <code>/admin_time_groups_remove_user</code> <i>group_key user_id</i> — удалить пользователя.  
➤ <code>/admin_time_groups_set_pos</code> <i>group_key user_id pos</i> — изменить позицию.  

<b>Удаление</b>
➤ <code>/admin_time_groups_delete</code> <i>group_key</i> — удалить группу.

───────────────────────

<b>Аргументы</b>
• <b>user_id</b> — числовой ID (Telegram или внутренний).  
• <b>pos</b> — позиция в группе (0 — первый слот).  
• <b>YYYY-MM-DD</b> — дата в ISO-формате.  
• <b>IANA_TZ</b> — валидный TZ (например, <code>Europe/Berlin</code>, <code>UTC</code>).  
• <b>period/days</b> — целое число дней (по умолчанию 8).  

<b>Эпоха:</b> базовая дата, от которой считается ротация.  
<b>TZ:</b> влияет на вычисление текущей даты при сменах.

───────────────────────

<b>Пример:</b>
<code>/admin_time_groups_create group_budyakov team_budyakov 2025-09-05 8</code>  
<code>/admin_time_groups_add_user group_budyakov 123456789 0</code>  
""".strip()
HELP_GROUPS_SHORT = """
<b>Доступные команды:</b>
➡️ /help_groups — полная справка
➡️ /admin_time_groups_list — список тайм-групп
➡️ /admin_users — все пользователи
️️➡️ /admin_time_profile_list — список профилей времени
➤ <code>/admin_time_groups_show</code> <i>group_key</i>
➤ <code>/admin_time_groups_add_user</code> <i>group_key</i> <i>user_id</i> <i>pos</i>
➤ <code>/admin_time_groups_remove_user</code> <i>group_key</i> <i>user_id</i>
➤ <code>/admin_time_groups_set_pos</code> <i>group_key</i> <i>user_id</i> <i>pos</i>
➤ <code>/admin_time_groups_set_period</code> <i>group_key</i> <i>days</i>
➤ <code>/admin_time_groups_delete</code> <i>group_key</i>
➤ <code>/admin_time_groups_create</code> <i>group_key</i> <i>profile_key</i> <i>YYYY-MM-DD</i> <i>period</i> <i>name</i>
""".strip()
HELP_TIME_PROFILES_FULL = """
<b>Доступные команды:</b>
➡️ /admin_users - список пользователей
➤ /admin_time_profile_list — профилей времени
➤ <code>/admin_time_profile_create</code> <i>key</i> <i>description</i> — создать профиль
➤ <code>/admin_time_profile_add_slot</code> <i>key</i> <i>start</i> <i>end</i> — добавить слот (например 09:00 18:00)
➤ <code>/admin_time_profile_clear_slots</code> <i>key</i> — очистить слоты
➤ <code>/admin_time_profile_show</code> <i>key</i> — показать детали
➤ <code>/admin_time_profile_delete</code> <i>key</i> — удалить профиль

💼 Профили «5/2» (будни)
Профили, у которых ключ начинается с <code>standart_</code> или <code>standard_</code> (например: <code>standart_vld</code>, <code>standard_5_2</code>), работают по правилу «только будни»:
• Пн–Пт — используется первый слот (позиция 0), обычно «Будний день».
• Сб–Вс — выходной (слоты не назначаются; /today, /ondate, /next пропускают эти дни).
• Ротация не нужна: <i>period</i> можно оставить 1.
Подсказка: назначьте в профиле слот с позицией 0 и нужным окном времени (например, 11:00–20:00) и привяжите такой профиль к группе.
""".strip()
HELP_TIME_PROFILES_SHORT = """
<b>Доступные команды:</b>
️➡️ /help_time_profiles — полная справка
️️➡️ /admin_time_profile_list — список профилей времени
➡️ /admin_time_groups_list — список тайм-групп
➡️ /admin_users — все пользователи
➤ <code>/admin_time_profile_show</code> <i>key</i>
➤ <code>/admin_time_profile_create</code> <i>key</i> <i>description</i>
➤ <code>/admin_time_profile_add_slot</code> <i>key</i> <i>pos</i> <i>start</i> <i>end</i>
➤ <code>/admin_time_profile_clear_slots</code> <i>key</i>
➤ <code>/admin_time_profile_delete</code> <i>key</i>
""".strip()
HELP_VACATIONS_FULL = """
🏖 <b>Отпуска</b>
 ➤ /vacation_add — добавить отпуск (бот спросит даты)
 ➤ /vacation_list — мои отпуска
 ➤ <code>/vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — изменить отпуск
 ➤ <code>/vacation_del</code> <i>&lt;id&gt;</i> — удалить отпуск
   Период: YYYY-MM | YYYY-MM-DD..YYYY-MM-DD | today/tomorrow | пусто = текущий месяц

 <b>Админ:</b>
 ➤ <code>/vacations_all</code> [<i>период</i>] — список всех отпусков
 ➤ <code>/admin_vacation_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — добавить отпуск пользователю
 ➤ <code>/admin_vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — изменить отпуск пользователя
 ➤ <code>/admin_vacation_del</code> <i>&lt;id&gt;</i> — удалить отпуск пользователя
""".strip()
HELP_VACATIONS_SHORT = """
<b>Доступные команды</b>
 ➡️ /help_vacations - полная справка
 ➡️ /vacation_list
 ➤ /vacation_add
 ➤ <code>/vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
 ➤ <code>/vacation_del</code> <i>&lt;id&gt;</i>
 ➡️ <code>/vacations_all</code> [<i>период</i>] (админ)
 ➤ <code>/admin_vacation_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
 ➤ <code>/admin_vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
 ➤ <code>/admin_vacation_del</code> <i>&lt;id&gt;</i>
""".strip()
HELP_SICK_FULL = """
🤒 <b>Больничные</b>
➤ <code>/sick_all</code> [<i>период</i>] (админ)
➤ /sick_add — добавить больничный (бот спросит даты)
➤ /sick_list — мои больничные
➤ <code>/sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — изменить больничный
➤ <code>/sick_del</code> <i>&lt;id&gt;</i> — удалить больничный

<b>Админ:</b>
➤ <code>/sick_all</code> [<i>период</i>] (админ)
➤ <code>/admin_sick_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
➤ <code>/admin_sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
➤ <code>/admin_sick_del</code> <i>&lt;id&gt;</i>
""".strip()
HELP_SICK_SHORT = """
🤒 <b>Больничные (коротко)</b>
➤ /sick_add
➤ /sick_list
➤ <code>/sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
➤ <code>/sick_del</code> <i>&lt;id&gt;</i>
➤ <code>/admin_sick_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
➤ <code>/admin_sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
➤ <code>/admin_sick_del</code> <i>&lt;id&gt;</i>
""".strip()
HELP_LOCATION_SHORT = """
➡️ /help_location — подробная справка
""".strip()
HELP_LOCATION_FULL = """
📍 <b>Локации (офис / дом)</b>

<b>Что это:</b>
Автоматическое распределение (офис/дом) с учётом:
• выходных и праздников,  
• дневных/ночных слотов,  
• парной ротации (🔷/🔶) и «активной пары»,  
• round-robin-тайбрейка и истории офис-дней.

<b>Легенда:</b>
• 🔷 — группа 1 (1 День / 1 Ночь)
• 🔶 — группа 2 (2 День / 2 Ночь)
• ♦️ — напарник в отпуске/больничном

<b>Правила назначения</b>
• Будний <i>1 День</i> → вся «Пара #1» (🔷) в офис.  
• Будний <i>2 День</i> → вся «Пара #2» (🔶) в офис.  
• <i>1 Ночь</i>, <i>2 Ночь</i> и <i>выходные/праздники</i> → в офис идёт <u>один</u> из <u>активной пары</u> по <u>минимуму</u> офис-дней (при равенстве — RR).  
• Если ротация выключена или пара неполная — фолбэки:  
  днём → двое с минимумом офис-дней; ночью/выходной → один с минимумом офис-дней.

<b>Команды</b>
➤ <code>/loc_next</code> [<i>N</i>|<i>YYYY-MM-DD</i> [<i>YYYY-MM-DD</i>]] [<i>group_key</i>] — план на период (до 30 дн.).  
  └ <i>N</i> — сколько дней вперёд (по умолчанию 7 дн.; макс 30).  
  └ <i>YYYY-MM-DD YYYY-MM-DD</i> — явный диапазон дат.  
  └ Можно добавить <i>group_key</i> или опустить — тогда берётся твоя группа.
➤ <code>/loc_assign</code> [<i>N</i>|<i>YYYY-MM-DD</i> [<i>YYYY-MM-DD</i>]] [<i>group_key</i>] — <b>админ</b>: записать назначения по правилам (🔷/🔶).  
  └ Без аргументов — 1 день вперёд для своей группы.  
  └ <i>N</i> — N дней вперёд (для своей или указанной группы).  
  └ <i>YYYY-MM-DD YYYY-MM-DD</i> — диапазон (включительно).  
  └ Будний день — вся активная пара 🏢 Офис.  
  └ Ночь/выходной — один 🏢 Офис (по минимуму офис-дней; RR при равенстве).
➤ <code>/loc_assign_manual</code> <i>[YYYY-MM-DD]</i> <i>user_id|@username</i> [<i>office|home</i>] [<i>group_key</i>] — <b>админ</b>: ручная правка.  
  └ Позволяет вручную назначить локацию конкретному пользователю.  
  └ Если дата не указана — используется сегодняшняя (предстоящая смена).  
  └ По умолчанию локация = 🏢 office, если не указано иное.  
  └ Если не задана группа — ищется по пользователю.
➤ <code>/loc_report</code> [<i>group_key</i>] <i>YYYY-MM-DD|YYYY-MM</i> [<i>YYYY-MM-DD|YYYY-MM</i>] — отчёт по офис-дням.  
  └ Можно пропустить <i>group_key</i> — тогда берётся твоя группа.  
  └ Поддерживает формат <i>YYYY-MM</i> (весь месяц).  
  └ Если конец месяца невалиден (например, 2025-11-31) — берётся фактический последний день.  
  └ Выводит «Имя Фамилия 🔗 @username — количество».
➤ <code>/loc_clear_future</code> [<i>group_key</i>] — удалить все будущие назначения (для своей или указанной группы).

<b>Примеры</b>
<code>/loc_next</code> — план на 7 дней вперёд для своей группы  
<code>/loc_next 30 vrn3</code> — план на 30 дней для vrn3  
<code>/loc_next 2025-11-01 2025-11-30 vrn3</code> — план на ноябрь для vrn3  
<code>/loc_assign 5 vrn3</code> — назначить на 5 дней вперёд  
<code>/loc_assign 2025-11-01 2025-11-15 vrn3</code> — назначить на диапазон  
<code>/loc_assign 2025-11-08 5 vrn3</code> — с даты + длительность  
<code>/loc_assign_manual 2025-10-12 @gematogenvrn home vrn3</code> — вручную поставить Будякову «дом» на дату  
<code>/loc_report vrn3 2025-10 2025-11</code> — сводка за октябрь–ноябрь  
<code>/loc_report 2025-10 2025-11</code> — то же, но группа берётся автоматически

<b>Настройка парной ротации (админ)</b>
• <code>/admin_rank_rotation_set &lt;group_key&gt; &lt;period_days&gt; &lt;YYYY-MM-DD&gt; [on|off]</code> — задать период/эпоху и включить/выключить.  
• <code>/admin_rank_rotation_show &lt;group_key&gt;</code> — показать текущее правило.  
• <code>/admin_rank_rotation_off &lt;group_key&gt; [on|off]</code> — переключить правило.
""".strip()
HELP_HOLIDAYS_SHORT = """
<b>Доступные команды (Праздники)</b>
➡️ /help_holidays — подробная справка
➤ <code>/holidays_status</code> — статус календаря (покрытие, источник, последняя правка)
➤ <code>/holidays_sync</code> <i>YYYY</i> [<i>YYYY…</i>] — обновить календарь за указанные годы
""".strip()
HELP_HOLIDAYS_FULL = """
📅 <b>Календарь праздников/выходных</b>

<b>Что это:</b>
Календарь хранится в таблице <code>ru_calendar(dt, is_working)</code> и материализованном представлении <code>ru_is_holiday_mv</code>.  
Локации используют его, чтобы отличать будни от выходных/праздников (для дневных/ночных правил и выбора «одного из пары»).

<b>Команды</b>
➤ <code>/holidays_status</code> — показывает источник, диапазон покрытых дат и когда календарь в последний раз обновлялся.  
➤ <code>/holidays_sync</code> <i>YYYY</i> [<i>YYYY…</i>] — пересчитать материализованный календарь для указанных лет.  
  └ Пример: <code>/holidays_sync 2025</code>

<b>Как это влияет на назначения</b>
• Выходные и официальные праздники считаются «не рабочими» и включают ночной/выходной режим выбора:  
  — в офис идёт <u>один</u> сотрудник из <u>активной пары</u> по минимуму офис-дней (при равенстве — RR).  
• Будние дни работают по дневным правилам (вся активная пара в офис).

<b>Примечания</b>
• Источник данных — <code>ru_is_holiday_mv</code> (генерируется из <code>ru_calendar</code> + правила выходных по ISO-неделе).  
• Для длительной стабильности рекомендуется периодически обновлять MV (например, раз в день планировщиком).
""".strip()
HELP_RANK_SHORT = """
<b>Доступные команды</b>
➡️ /help_rank — подробная справка
➤ <code>/rank_set &lt;group_key&gt; &lt;user_id&gt; &lt;1|2|3&gt;</code> — задать ранг (только админы)
➤ <code>/rank_list &lt;group_key&gt;</code> — список рангов по группе
"""
HELP_RANK_FULL = """<b>Ранги участников</b>

Ранги задают «вес»/роль участника в группе дежурств и учитываются при показе и алгоритмах распределения.
Доступны значения:
• <b>1 — лидер</b>
• <b>2 — специалист</b>
• <b>3 — младший</b>
Если ранг не задан явно, считается равным 2.

<b>Команды</b>
➤ <code>/rank_set &lt;group_key&gt; &lt;user_id&gt; &lt;1|2|3&gt;</code> — установить/изменить ранг пользователя в группе (только админы).
➤ <code>/rank_list &lt;group_key&gt;</code> — показать все ранги в группе с указанием <code>user_id</code>.

<b>Параметры</b>
➤ <code>group_key</code> — ключ группы дежурств (строка).
➤ <code>user_id</code> — числовой ID пользователя (как в Telegram).
➤ <code>rank</code> — одно из значений: 1, 2 или 3.

<b>Примеры</b>
➤ <code>/rank_set support 123456789 1</code> — пользователь 123456789 станет «лидером» в группе <code>support</code>.
➤ <code>/rank_list support</code> — все ранги в группе <code>support</code>.

<b>Права</b>
Команда <code>/rank_set</code> доступна только администраторам. Если прав нет, бот ответит «Только для админов».

<b>Примечания</b>
• Ранг хранится отдельно для каждой группы (<code>group_key</code>).
• В некоторых режимах может применяться ротация рангов по правилам группы (если включена админом). В таком случае эффективный ранг может временно «переключаться» согласно настройкам ротации."""
HELP_RANK_ROTATION_SHORT = """
<b>Доступные команды:</b>
➡️ /help_rank_rotation — подробная справка
➤ <code>/admin_rank_rotation_set <i>group_key</i> <i>period_days</i> <i>YYYY-MM-DD</i> <i>[on|off]</i> </code>  
➤ <code>/admin_rank_rotation_show <i>group_key</i> </code>  
➤ <code>/admin_rank_rotation_off <i>group_key</i> <i>[on|off]</i> </code> 
➤ <code>/pair_stats <i>group_key</i> <i>date_from</i> <i>date_to</i> </code>
""".strip()
HELP_RANK_ROTATION_FULL = """
🔁 <b>Парная ротация по рангам (rank_rotation)</b>

<b>Зачем:</b>
Автоматически формировать дневные пары «СП (ранг=1) + С (ранг=2)» по группе с циклическим сдвигом.
Используется внутри <code>/loc_assign</code> для будних дневных слотов: выбирается ровно одна пара СП+С.
Пара логируется в <code>pair_work_log</code>, чтобы считать статистику совместных смен.

<b>Как это работает:</b>
• Конфигурация на группу хранится в <code>rank_rotation_rules</code>: <i>epoch</i> (дата старта), <i>period_days</i> (шаг сдвига), <i>is_enabled</i>.  
• Смещение: <code>offset = floor((on_date - epoch)/period_days)</code>.  
• Для всех участников дневного слота отделяются ранги: 1 → «СП», 2 → «С» (ранги берутся из duty_admin_repository или конфигурации тайм-группы).  
• Каждому «СП» ставится «С» по кругу с учётом <code>offset</code>.  
• Из всех получившихся пар выбирается <b>лучшая</b> по минимальной сумме офис-дней (история берётся из <code>location_assignments</code>), после чего обоим назначается «🏢 Офис».  
• Если пар не получилось (нет СП/С или нет конфигурации) — жёсткий фолбэк: выбираются двое с минимальными офис-днями (с приоритетом СП и С).  
• В выходные/праздники и в ночные слоты парная ротация не применяется: остаётся ровно один «🏢 Офис» по правилу «у кого больше офис-дней» (при равенстве — RR-курсор).

<b>Команды (только админы):</b>
➤ <code>/admin_rank_rotation_set</code> <i>group_key</i> <i>period_days</i> <i>YYYY-MM-DD</i> [<i>on|off</i>] — создать/обновить правило  
➤ <code>/admin_rank_rotation_show</code> <i>group_key</i> — показать активное правило  
➤ <code>/admin_rank_rotation_off</code> <i>group_key</i> [<i>on|off</i>] — быстро включить/выключить  
➤ <code>/pair_stats</code> <i>group_key</i> <i>date_from</i> <i>date_to</i> — статистика: сколько дней вместе отработала каждая пара

<b>Примеры:</b>
<code>/admin_rank_rotation_set vrn3 7 2025-10-01 on</code> — ротация по группе <code>vrn3</code> со сдвигом каждые 7 дней, включено  
<code>/admin_rank_rotation_show vrn3</code> — показать правило  
<code>/admin_rank_rotation_off vrn3 off</code> — выключить  
<code>/pair_stats vrn3 2025-10-01 2025-10-31</code> — пары за октябрь

<b>Требования к данным:</b>
• Ранги: 1=старший специалист, 2=специалист, 3=джуниор. Для парной ротации нужны участники с рангами 1 и 2.  
• Тайм-группа и слоты: парная ротация применяется только к участникам дневного слота в будний день.  
• Таблицы БД: <code>rank_rotation_rules</code>, <code>pair_work_log</code>, <code>location_assignments</code>, <code>ru_is_holiday</code>.

<b>Подсказки:</b>
• Проверьте, что в нужной группе действительно есть минимум один участник ранга 1 и один ранга 2 в дневном слоте выбранной даты.  
• Если правило выключено или некорректно заполнено (<i>epoch</i>/<i>period_days</i>), алгоритм переключится на фолбэк без пар.  
""".strip()
HELP_DUTIES_SHORT = '''
<b>🪄 Быстрые команды</b>

📅 Назначения
• /duties_now — кто на дежурстве сейчас
• /duties_all [дата] — все назначения на день
• /who_on_shift_now — кто в смене прямо сейчас

⚙️ Автоназначение
• /assignw_now — «на сейчас» по весам и рангам
• /assignw <YYYY-MM-DD> [group_key] — на дату
• /assignw_recon — перераспределить при AFK/смене состава

📚 Каталог
• /duties_catalog — список обязанностей
• /duty_show <key> — карточка обязанности

🏅 Ранги
• /rank_list — текущие ранги
• /rank_set <group user rank> — задать ранг

👤 Личные
• /my_duties — мои задачи сегодня
• /my_duties_next — ближайшие мои назначения
'''.strip()
HELP_DUTIES_FULL = '''
🧩 <b>MagicDuty — управление обязанностями</b>

<b>Каталог обязанностей</b>  
• /duties_catalog [поиск] — показать каталог (вес, ранг, семейство)  
• /duty_show &lt;key&gt; — карточка одной обязанности  
• /duty_import — загрузить CSV  
• /duty_export — выгрузить CSV  
Формат CSV:  
<code>key,title,weight,office_required,target_rank,min_rank,family_key,handoff_policy,description</code>

<b>Просмотр назначений</b>  
• /duties_all [YYYY-MM-DD] [group_key] — назначения на дату  
• /duties_now [group_key] — назначения прямо сейчас  
• /who_on_shift_now [group_key] — кто реально в смене  
Каждое назначение теперь «привязано» к <b>сегменту</b> —  
например, <i>Сегмент День Воронеж</i> или <i>Сегмент Ночь Владивосток</i>.

<b>Автораспределение</b>  
• /assign_duties — справедливое (по истории 30 дней)  
• /assign_duties_rr — Round-Robin на дату  
• /assign_duties_now [group_key] — Round-Robin «на сейчас»  
• /assignw &lt;YYYY-MM-DD&gt; [group_key] — весовое распределение по весам и рангам  
• /assignw_now — глобальное весовое распределение «на сейчас»  
• /assignw_recon — реконфигурация, если кто-то ушёл AFK или сменился состав  
 ⤷ алгоритм сохраняет семейства задач: передаёт целиком пакеты обязанностей преемнику  
  (с учётом липкости и приоритета семейства)

<b>Семейства и handoff-policy</b>  
Каждая обязанность имеет <b>family_key</b> — логическую группу (например, «мониторинг»).  
Поле <b>handoff_policy</b> задаёт стратегию передачи:  
• <code>segment_end</code> — передача в конце сегмента  
• <code>sticky_until_invalid</code> — липкое закрепление  
• <code>handoff_to_successor</code> — передача преемнику (при реконфигурации)

<b>Ранги</b>  
• /rank_list — показать ранги участников  
• /rank_set &lt;group_key user_id rank(1..3)&gt; — задать вручную  
 1 = leader, 2 = specialist, 3 = junior

<b>Сброс</b>  
• /duties_reset_today [group_key] — удалить назначения за сегодня (админ)

<b>Личные</b>  
• /my_duties [дата] — мои назначения (формат DD.MM или YYYY-MM-DD)  
• /my_duties_next — ближайшие мои задачи  

<b>Регламент для админов</b>  
1️⃣ 🕗 Начало смены — <code>/assignw_now</code> (создать назначения «на сейчас»).  
2️⃣ 🔄 Изменился состав — <code>/assignw_recon</code> (обновить активных).  
3️⃣ 📊 Отчёт — <code>/duties_all [YYYY-MM-DD]</code> (показать назначения).  

<b>Примеры</b>  
— <code>/assignw 2025-10-29 vrn3</code> → назначить обязанности на 29 октября для группы Воронеж-3  
— <code>/assignw_now</code> → немедленно перераспределить все активные группы  
— <code>/assignw_recon</code> → снять AFK и передать их семейства преемникам  
— <code>/duties_all 2025-10-29 vdk1</code> → показать назначения Владивостока на 29 октября  
— <code>/my_duties_next</code> → показать, что у тебя дальше по плану
'''.strip()
