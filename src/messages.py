# ── Static ────────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "🐍 **О боте:**\n"
    "Используем самые современные технологии обхода блокировок — быстро, надёжно и без лишних сложностей.\n\n"
    "✅ **Без ограничений по трафику** для стандартных тарифов\n"
    "📖 **Авторские мануалы** по настройке в закрытом Telegram-канале *(доступ при покупке через Tribute)*\n"
    "🛠 **Поддержка** при возникновении любых проблем\n"
    "💯 Своим продуктом я пользуюсь лично\n\n"
    "━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📦 **Тарифы:**\n\n"
    "🔹 **Стандартный** — подходит для повседневного использования:\n"
    "• До 5 устройств одновременно\n"
    "• Без ограничений по трафику\n"
    "• Стабильный обход большинства блокировок\n\n"
    "💎 **Premium** — для обхода белых списков *(когда на улице не работает ничего, кроме ВК и Яндекса)*:\n"
    "• Специальная конфигурация для мобильных сетей\n"
    "• Лимит трафика: **50 ГБ в месяц**\n\n"
    "💡 **Стандартный тариф подходит в 9 из 10 случаев.** Premium нужен только тогда, когда интернет ограничен на уровне оператора связи."
)

CONNECT_INSTRUCTIONS = (
    "🌐 **Подключение VPN**\n\n"
    "━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📌 **Какой тариф выбрать?**\n\n"
    "🔹 **Стандартный** — ваш выбор по умолчанию:\n"
    "Отлично работает дома, в офисе и при хорошем мобильном интернете.\n"
    "Без ограничений по трафику, до 5 устройств.\n\n"
    "💎 **Premium** — только при включении белых списков:\n"
    "Когда на улице или в транспорте не работает ничего, кроме ВК, Яндекса и Госуслуг — вот тогда переключайтесь на Premium.\n"
    "Лимит трафика: 50 ГБ в месяц.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📲 **Как подключиться:**\n\n"
    "**1.** Нажмите кнопку «Подключиться» или отсканируйте QR-код\n"
    "→ Откроется страница с вашим VPN-профилем\n\n"
    "**2.** Пролистайте страницу вниз\n"
    "→ Найдите кнопки для вашей платформы:\n"
    "    📱 Android\n"
    "    🍏 iPhone (iOS)\n\n"
    "**3.** Выберите устройство и установите приложение\n\n"
    "✅ Готово — VPN включён! 🚀\n\n"
    "💡 Не получилось? Попробуйте другое приложение из списка."
)

SUB_EXPIRY_WARNING = (
    "⏰ **Подписка истекает через 24 часа!**\n\n"
    "Продлите её, чтобы не потерять доступ к VPN."
)

PREM_EXPIRY_WARNING = (
    "⏰ **Premium-подписка истекает через 24 часа!**\n\n"
    "Продлите её, чтобы не потерять доступ к VPN."
)

SUB_EXPIRED = (
    "❌ **Подписка истекла**\n\n"
    "VPN-профиль был удалён. Оформите новую подписку, чтобы снова получить доступ."
)

TRIBUTE_CANCELLED = (
    "ℹ️ **Подписка Tribute отменена**\n\n"
    "Доступ сохраняется до конца оплаченного периода."
)


# ── Dynamic ───────────────────────────────────────────────────────────────────

def welcome(bot_name: str) -> str:
    return (
        f"👋 Добро пожаловать в `{bot_name}`!\n\n"
        "🎁 Вам активирован **бесплатный тестовый период на 3 дня** — пользуйтесь!\n\n"
        "📖 Узнайте о тарифах в разделе **ℹ️ Помощь**.\n\n"
        "💡 Коротко: **Стандартный** тариф подходит для повседневного использования. "
        "**Premium** нужен, когда оператор включает белые списки и не работает ничего, кроме ВК и Яндекса."
    )


def payment_success(action_type: str, months: int, suffix: str, tier_label: str) -> str:
    return (
        f"✅ **Оплата прошла успешно!**\n\n"
        f"📦 Тариф: **{tier_label}**\n"
        f"🗓 Подписка {action_type} на **{months} {suffix}**\n\n"
        "Спасибо за покупку! 🎉"
    )


def admin_payment_notification(
    action_type: str, full_name: str, telegram_id: int,
    months: int, suffix: str, tier_label: str, final_price: int,
) -> str:
    return (
        f"💰 {action_type.capitalize()} подписка — "
        f"`{full_name}` | `{telegram_id}` "
        f"на {months} {suffix} ({tier_label}) — **{final_price}₽**"
    )


def admin_menu_text(total: int, with_sub: int, without_sub: int, online_count: int) -> str:
    return (
        "⚙️ **Административное меню**\n\n"
        f"👥 **Всего пользователей:** `{total}`\n"
        f"✅ **С подпиской:** `{with_sub}` | ❌ **Без подписки:** `{without_sub}`\n"
        f"🟢 **Онлайн:** `{online_count}` | ⚫️ **Офлайн:** `{with_sub - online_count}`"
    )


def broadcast_result(success: int, failed: int, total: int) -> str:
    return (
        f"📨 **Результаты рассылки:**\n\n"
        f"✅ Успешно: `{success}`\n"
        f"❌ Не удалось: `{failed}`\n"
        f"📊 Всего: `{total}`"
    )


def network_stats_text(upload: str, upload_size: str, download: str, download_size: str) -> str:
    return (
        "📊 **Статистика сети:**\n\n"
        f"🔼 Upload — `{upload} {upload_size}`\n"
        f"🔽 Download — `{download} {download_size}`"
    )


def fix_profiles_result(fixed_db_count: int, success_count: int, fail_count: int, users_len: int) -> str:
    return (
        f"🔧 **Исправление профилей завершено**\n\n"
        f"📝 Исправлено дат в БД: `{fixed_db_count}`\n"
        f"✅ Обновлено профилей в 3x-ui: `{success_count}`\n"
        f"❌ Ошибок: `{fail_count}`\n\n"
        f"📋 Всего проверено: `{users_len}` пользователей"
    )


def check_subs_result(stats: dict) -> str:
    if "error" in stats:
        return f"❌ **Ошибка при проверке подписок:**\n\n{stats['error']}"

    text = (
        f"🔍 **Проверка подписок завершена**\n\n"
        f"📊 **Статистика:**\n"
        f"• Клиентов в 3x-ui: `{stats['total_3xui']}`\n"
        f"• Пользователей в БД: `{stats['total_db']}`\n"
        f"• Совпадают: `{stats['matched']}` ✅\n"
        f"• Расхождения: `{stats['mismatch']}` ⚠️\n"
        f"• Исправлено: `{stats['fixed']}` 🔧\n"
        f"• Нет в БД: `{stats['not_in_db']}` ℹ️\n\n"
    )

    problems = [d for d in stats['details'] if d['status'] in ('mismatch', 'fix_failed', 'fix_error')]
    if problems:
        text += f"⚠️ **Проблемы ({len(problems)}):**\n\n"
        for i, problem in enumerate(problems[:10], 1):
            status_emoji = {'mismatch': '⚠️', 'fix_failed': '❌', 'fix_error': '🛑'}.get(problem['status'], '❓')
            text += f"{i}. {status_emoji} `{problem['email']}` (inbound {problem.get('inbound_id', '?')})\n"
            if problem['status'] == 'fix_error':
                text += f"   Ошибка: {problem.get('error', 'Неизвестно')}\n"
            text += "\n"
        if len(problems) > 10:
            text += f"_...и ещё {len(problems) - 10} проблем_\n\n"

    fixed = [d for d in stats['details'] if d['status'] == 'fixed']
    if fixed:
        text += f"✅ **Исправлено ({len(fixed)}):**\n\n"
        for i, fix in enumerate(fixed[:5], 1):
            text += f"{i}. `{fix['email']}`\n"
        if len(fixed) > 5:
            text += f"_...и ещё {len(fixed) - 5}_\n\n"

    return text


def delete_user_confirm(
    full_name: str, username: str, telegram_id: int,
    reg_date: str, sub_end: str, has_profile: bool,
) -> str:
    return (
        f"⚠️ **Подтвердите удаление пользователя:**\n\n"
        f"👤 Имя: `{full_name}`\n"
        f"📱 Username: `{username}`\n"
        f"🆔 Telegram ID: `{telegram_id}`\n"
        f"📅 Регистрация: `{reg_date}`\n"
        f"⏰ Подписка до: `{sub_end}`\n"
        f"🔧 Профиль: `{'Есть' if has_profile else 'Нет'}`\n\n"
        f"❗️ **Это действие необратимо!**"
    )


def delete_user_success(telegram_id: int) -> str:
    return (
        f"✅ **Пользователь удалён**\n\n"
        f"🆔 Telegram ID: `{telegram_id}`\n\n"
        "Профили в 3x-ui также удалены (если существовали)."
    )


def delete_user_failure(telegram_id: int) -> str:
    return (
        f"❌ **Ошибка удаления**\n\n"
        f"🆔 Telegram ID: `{telegram_id}`\n\n"
        "Пользователь не найден в базе данных."
    )


def tribute_sub_activated(action: str, tier_label: str, months: int, suffix: str) -> str:
    return (
        f"✅ **Подписка {action} через Tribute!**\n\n"
        f"📦 Тариф: **{tier_label}** | 🗓 Срок: {months} {suffix}\n\n"
        "Используйте /connect для получения конфигурации."
    )


def tribute_admin_notify(action: str, telegram_id: int, months: int, suffix: str, tier_label: str) -> str:
    return (
        f"🔔 Tribute: подписка {action} — `{telegram_id}` "
        f"на {months} {suffix} ({tier_label})"
    )


def tribute_digital_activated(product_name: str, tier_label: str, hours: int) -> str:
    return (
        f"✅ **Подписка активирована через Tribute!**\n\n"
        f"🛒 Товар: {product_name} | 📦 Тариф: {tier_label} | ⏱ Срок: {hours}ч\n\n"
        "Используйте /connect для получения конфигурации."
    )


def tribute_digital_admin_notify(telegram_id: int, product_name: str, tier_label: str, hours: int) -> str:
    return (
        f"🔔 Tribute: цифровой товар — `{telegram_id}` "
        f"«{product_name}» ({tier_label}, {hours}ч)"
    )
