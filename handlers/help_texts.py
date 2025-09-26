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
• /today — смены на сегодня
• /tomorrow — смены на завтра
• <code>/ondate</code> <i>DD.MM[.YYYY]</i> — кто дежурит в указанную дату

👥 Пользователи:
• /admin_pending — список ожидающих
• <code>/admin_approve</code> <i>user_id</i> [<i>group_key</i>] — одобрить
• /admin_users — все пользователи
• <code>/admin_removeuser</code> <i>user_id</i> — удалить
• <code>/admin_set_group</code> <i>user_id</i> <i>group_key</i> — назначить группу
• <code>/admin_unset_group</code> <i>user_id</i> — снять группу
• <code>/admin_list_group</code> <i>group_key</i> — пользователи в группе
• /admin_update_all_users — обновить профили (username/имена)

👷 Группы (тайм-группы):
• /admin_time_groups_list — список групп
• <code>/admin_time_groups_show</code> <i>group_key</i> — подробности по группе
• <code>/admin_time_groups_create</code> <i>group_key</i> <i>profile_key</i> <i>YYYY-MM-DD</i> <i>period</i> — создать/обновить
• <code>/admin_time_groups_add_user</code> <i>group_key</i> <i>user_id</i> <i>pos</i> — добавить пользователя
• <code>/admin_time_groups_remove_user</code> <i>group_key</i> <i>user_id</i> — удалить пользователя
• <code>/admin_time_groups_set_pos</code> <i>group_key</i> <i>user_id</i> <i>pos</i> — изменить позицию
• <code>/admin_time_groups_set_period</code> <i>group_key</i> <i>days</i> — период ротации
• <code>/admin_time_groups_set_tz</code> <i>group_key</i> <i>IANA_TZ</i> — часовой пояс
• <code>/admin_time_groups_delete</code> <i>group_key</i> — удалить группу

⏱ Тайм-профили:
• /admin_time_profile_list — список профилей
• <code>/admin_time_profile_create</code> <i>key</i> <i>description</i> — создать профиль
• <code>/admin_time_profile_add_slot</code> <i>key</i> <i>start</i> <i>end</i> — добавить слот (например 09:00 18:00)
• <code>/admin_time_profile_clear_slots</code> <i>key</i> — очистить слоты
• <code>/admin_time_profile_show</code> <i>key</i> — показать детали
• <code>/admin_time_profile_delete</code> <i>key</i> — удалить профиль

🏖 Отпуска:
• /vacation_add — добавить отпуск (бот спросит даты)
• /vacation_list — мои отпуска
• /vacation_edit — изменить отпуск
• /vacation_del — удалить отпуск
• /admin_vacation_add — добавить отпуск пользователю (админ)
• /admin_vacation_edit — изменить отпуск пользователя (админ)
• /admin_vacation_del — удалить отпуск пользователя (админ)

🤒 Больничные:
• /sick_add — добавить больничный (бот спросит даты)
• /sick_list — мои больничные
• /sick_edit — изменить больничный
• /sick_del — удалить больничный
• /admin_sick_add — добавить больничный пользователю (админ)
• /admin_sick_edit — изменить больничный пользователя (админ)
• /admin_sick_del — удалить больничный пользователя (админ)
""".strip()
HELP_MAIN_SHORT = """
❓ <b>Справка — основные команды</b>

👋 <b>Повседневное</b>
• /today — смены на сегодня
• /tomorrow — смены на завтра
• <code>/ondate</code> <i>DD.MM[.YYYY]</i> — кто дежурит в указанную дату

⚙️ <b>Конфигурация</b>:
• /admin_users - список пользователей
• /admin_time_groups_list — список групп
• /admin_time_profile_list — список профилей
• /vacations_all [<i>период</i>] — список всех отпусков
• /sick_all [<i>период</i>] (админ)

• /help_groups — группы (админ)
• /help_vacations — отпуска
• /help_sick — больничные
• /help_duties — обязанности          
• /help_admin_all — все админ-команды одним списком
""".strip()
HELP_USERS_SHORT = """
<b>Доступные команды:</b>
➡️ /help_users — полная справка
➡️ /admin_pending — ожидающие авторизации
➡️ /admin_time_groups_list — список тайм-групп
️️➡️ /admin_time_profile_list — список профилей времени
➤ <code>/admin_approve</code> <i>user_id</i>
➤ <code>/admin_removeuser</code> <i>user_id</i>
""".strip()
HELP_USERS_FULL = """
👥 <b>Работа с пользователями</b>
➡️ /admin_users — все пользователи
➡️ /admin_pending — список ожидающих одобрения
➤ <code>/admin_approve</code> <i>user_id</i> — одобрить
➤ <code>/admin_removeuser</code> <i>user_id</i> — удалить пользователя

🔄 <b>Служебное</b>
• /admin_update_all_users — обновить профили (username/имена)
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
• <code>/admin_time_groups_list</code> — список групп (кратко).
• <code>/admin_time_groups_show</code> <i>group_key</i> — подробности по группе.

<b>Создание и настройки</b>
• <code>/admin_time_groups_create</code> <i>group_key profile_key YYYY-MM-DD period</i> — создать/обновить группу.
   ├ <b>group_key</b> — ключ (например, <code>group_budyakov</code>)  
   ├ <b>profile_key</b> — связанный профиль (например, <code>team_budyakov</code>)  
   ├ <b>YYYY-MM-DD</b> — дата эпохи (например, <code>2025-09-05</code>)  
   └ <b>period</b> — период ротации в днях (например, <code>8</code>)  

• <code>/admin_time_groups_set_period</code> <i>group_key days</i> — сменить период.  
• <code>/admin_time_groups_set_tz</code> <i>group_key IANA_TZ</i> — сменить часовой пояс (например, <code>Europe/Moscow</code>).

<b>Участники</b>
• <code>/admin_time_groups_add_user</code> <i>group_key user_id pos</i> — добавить пользователя.  
• <code>/admin_time_groups_remove_user</code> <i>group_key user_id</i> — удалить пользователя.  
• <code>/admin_time_groups_set_pos</code> <i>group_key user_id pos</i> — изменить позицию.  

<b>Удаление</b>
• <code>/admin_time_groups_delete</code> <i>group_key</i> — удалить группу.

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
<code>/admin_time_groups_set_tz group_budyakov Europe/Moscow</code>  
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
➤ <code>/admin_time_groups_set_tz</code> <i>group_key</i> <i>IANA_TZ</i>
➤ <code>/admin_time_groups_delete</code> <i>group_key</i>
➤ <code>/admin_time_groups_create</code> <i>group_key</i> <i>profile_key</i> <i>YYYY-MM-DD</i> <i>period</i> <i>name</i>
""".strip()
HELP_TIME_PROFILES_FULL = """
<b>Доступные команды:</b>
➡️ /admin_users - список пользователей
• /admin_time_profile_list — профилей времени
• <code>/admin_time_profile_create</code> <i>key</i> <i>description</i> — создать профиль
• <code>/admin_time_profile_add_slot</code> <i>key</i> <i>start</i> <i>end</i> — добавить слот (например 09:00 18:00)
• <code>/admin_time_profile_clear_slots</code> <i>key</i> — очистить слоты
• <code>/admin_time_profile_show</code> <i>key</i> — показать детали
• <code>/admin_time_profile_delete</code> <i>key</i> — удалить профиль
""".strip()
HELP_TIME_PROFILES_SHORT = """
<b>Доступные команды:</b>
️➡️ /help_time_profiles — полная справка
️️➡️ /admin_time_profile_list — список профилей времени
➡️ /admin_time_groups_list — список тайм-групп
➡️ /admin_users — все пользователи
➤ <code>/admin_time_profile_show</code> <i>key</i>
➤ <code>/admin_time_profile_create</code> <i>key</i> <i>description</i>
➤ <code>/admin_time_profile_add_slot</code> <i>key</i> <i>start</i> <i>end</i>
➤ <code>/admin_time_profile_clear_slots</code> <i>key</i>
➤ <code>/admin_time_profile_delete</code> <i>key</i>
""".strip()
HELP_VACATIONS_FULL = """
🏖 <b>Отпуска</b>
 • /vacation_add — добавить отпуск (бот спросит даты)
 • /vacation_list — мои отпуска
 • <code>/vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — изменить отпуск
 • <code>/vacation_del</code> <i>&lt;id&gt;</i> — удалить отпуск
   Период: YYYY-MM | YYYY-MM-DD..YYYY-MM-DD | today/tomorrow | пусто = текущий месяц

 <b>Админ:</b>
 • <code>/vacations_all</code> [<i>период</i>] — список всех отпусков
 • <code>/admin_vacation_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — добавить отпуск пользователю
 • <code>/admin_vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — изменить отпуск пользователя
 • <code>/admin_vacation_del</code> <i>&lt;id&gt;</i> — удалить отпуск пользователя
""".strip()
HELP_VACATIONS_SHORT = """
🏖 <b>Отпуска (коротко)</b>
 • /vacation_add
 • /vacation_list
 • <code>/vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
 • <code>/vacation_del</code> <i>&lt;id&gt;</i>
 • <code>/vacations_all</code> [<i>период</i>] (админ)
 • <code>/admin_vacation_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
 • <code>/admin_vacation_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
 • <code>/admin_vacation_del</code> <i>&lt;id&gt;</i>
""".strip()
HELP_SICK_FULL = """
🤒 <b>Больничные</b>
• <code>/sick_all</code> [<i>период</i>] (админ)
• /sick_add — добавить больничный (бот спросит даты)
• /sick_list — мои больничные
• <code>/sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i> — изменить больничный
• <code>/sick_del</code> <i>&lt;id&gt;</i> — удалить больничный

<b>Админ:</b>
• <code>/sick_all</code> [<i>период</i>] (админ)
• <code>/admin_sick_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
• <code>/admin_sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
• <code>/admin_sick_del</code> <i>&lt;id&gt;</i>
""".strip()
HELP_SICK_SHORT = """
🤒 <b>Больничные (коротко)</b>
• /sick_add
• /sick_list
• <code>/sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
• <code>/sick_del</code> <i>&lt;id&gt;</i>
• <code>/admin_sick_add</code> <i>&lt;user_id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
• <code>/admin_sick_edit</code> <i>&lt;id&gt; YYYY-MM-DD YYYY-MM-DD [комментарий]</i>
• <code>/admin_sick_del</code> <i>&lt;id&gt;</i>
""".strip()
HELP_ADMIN_ALL_FULL = """
🛡 <b>Все админ-команды</b>

👥 <b>Пользователи</b>:
• /admin_pending
• <code>/admin_approve</code> <i>user_id</i> [<i>group_key</i>]
• /admin_users
• <code>/admin_removeuser</code> <i>user_id</i>
• /admin_update_all_users
• <code>/admin_set_group</code> <i>user_id</i> <i>group_key</i>
• <code>/admin_unset_group</code> <i>user_id</i>
• <code>/admin_list_group</code> <i>group_key</i>

👷 <b>Группы</b>:
• /admin_time_groups_list
• <code>/admin_time_groups_show</code> <i>group_key</i>
• <code>/admin_time_groups_create</code> <i>group_key</i> <i>profile_key</i> <i>YYYY-MM-DD</i> <i>period</i>
• <code>/admin_time_groups_add_user</code> <i>group_key</i> <i>user_id</i> <i>pos</i>
• <code>/admin_time_groups_remove_user</code> <i>group_key</i> <i>user_id</i>
• <code>/admin_time_groups_set_pos</code> <i>group_key</i> <i>user_id</i> <i>pos</i>
• <code>/admin_time_groups_set_period</code> <i>group_key</i> <i>days</i>
• <code>/admin_time_groups_set_tz</code> <i>group_key</i> <i>IANA_TZ</i>
• <code>/admin_time_groups_delete</code> <i>group_key</i>

⏱ <b>Тайм-профили</b>:
• /admin_time_profile_list
• <code>/admin_time_profile_create</code> <i>key</i> <i>description</i>
• <code>/admin_time_profile_add_slot</code> <i>key</i> <i>start</i> <i>end</i>
• <code>/admin_time_profile_clear_slots</code> <i>key</i>
• <code>/admin_time_profile_show</code> <i>key</i>
• <code>/admin_time_profile_delete</code> <i>key</i>

🏖 <b>Отпуска</b>:
• /vacation_add, /vacation_list, /vacation_edit, /vacation_del
• /admin_vacation_add, /admin_vacation_edit, /admin_vacation_del

🤒 <b>Больничные</b>:
• /sick_add, /sick_list, /sick_edit, /sick_del
• /admin_sick_add, /admin_sick_edit, /admin_sick_del
""".strip()
HELP_DUTIES_SHORT = '''
🧩 <b>Обязанности (коротко)</b>
• /duties_catalog [поиск] — список обязанностей
• <code>/duty_show</code> <i>key</i> — карточка одной обязанности
• /duty_import — загрузить каталог из CSV
• /duty_export — выгрузить каталог в CSV
• /assign_duties — авторспределение на сегодня (справедливость по истории)
• /assign_duties_rr — авторспределение Round-Robin
• /rank_list — ранги участников по группам
• <code>/rank_set</code> <i>group_key</i> <i>user_id</i> <i>rank(1..3)</i>
• <code>/duty_exclude</code> <i>user_id</i> <i>YYYY-MM-DD..YYYY-MM-DD</i> [<i>group_key</i>] [<i>reason</i>]
• <code>/duty_exclude_del</code> <i>id</i>
• /duty_exclude_list — активные исключения
• /my_duties [дата] — мои назначения на сегодня/дату
• /my_duties_next — ближайшие мои назначения
• /my_duties — мои обязанности (можно дату: DD.MM[.YYYY] или YYYY-MM-DD)
'''.strip()
HELP_DUTIES_FULL = '''
🧩 <b>Обязанности</b>

<b>Каталог</b>
• /duties_catalog [поиск] — показать список (вес, офисность, мин/таргет ранг)
• <code>/duty_show</code> <i>key</i> — подробная карточка
• /my_duties [дата] — мои назначения на сегодня/дату
• /my_duties_next — ближайшие мои назначения
• /my_duties — мои обязанности (можно дату: DD.MM[.YYYY] или YYYY-MM-DD)

<b>Импорт/экспорт каталога</b>
• /duty_import — загрузить CSV
• /duty_export — выгрузить CSV
Формат CSV: <code>key,title,weight,office_required,target_rank,min_rank,description</code>
Примечания:
— <code>office_required</code>: 1/0, yes/no, true/false, да/нет
— <code>target_rank/min_rank</code>: целые числа или пусто

<b>Автораспределение</b>
• /assign_duties — справедливая выдача по истории (у кого меньше назначений, того вперед)
• /assign_duties_rr — алгоритм Round-Robin по каждому duty

<b>Ранги</b>
• /rank_list — показать текущие ранги по группам
• <code>/rank_set</code> <i>group_key</i> <i>user_id</i> <i>rank(1..3)</i> — 1=lead, 2=specialist, 3=junior

<b>Исключения</b>
• <code>/duty_exclude</code> <i>user_id</i> <i>YYYY-MM-DD..YYYY-MM-DD</i> [<i>group_key</i>] [<i>reason</i>]
• <code>/duty_exclude_del</code> <i>id</i>
• /duty_exclude_list — посмотреть активные исключения
'''.strip()





