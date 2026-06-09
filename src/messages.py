# ── Static ────────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "О боте:\n "
    "Самые современные технологии обходов.\n"
    "Нет ограничений по траффику для стандартных тарифов.\n"
    "Авторские мануалы по настройке в закрытом tg канале(доступ при покупке через tribute).\n"
    "Поддержка в случае возникновения проблем. Своим продуктом я пользуюсь лично.\n"
    "Be smart, be wise, be a snake.\n\n"
    "О различиях подписок:\n"
    "Стандартная подписка включает подключение до 5 устройств без лимитов по траффику.\n"
    "Premium подписка предлагает конфигурацию для обхода белых списков. "
    "Думаю многих бесит, что выйдя на улицу, пользоваться ничем кроме ВК и Яндекса невозможно. "
    "Данная конфигурация создана именно для вас. Есть лишь одно ограничение: 50ГБ траффика в месяц."
)

CONNECT_INSTRUCTIONS = (
    "📲 Как подключить VPN\n"
    "1. Нажмите кнопку «Подключиться» или отсканируйте QR код\n"
    "Откроется страница с вашим VPN-профилем.\n\n"
    "2. Пролистайте страницу вниз\n"
    "Найдите кнопки с вашей операционной системой:\n"
    "📱 Android\n"
    "🍏 iPhone (iOS)\n\n"
    "3. Выберите своё устройство и приложение\n\n"
    "✅ Готово! VPN включён 🚀\n\n"
    "💡 Если не получилось — попробуйте другое приложение\n"
)

SUB_EXPIRY_WARNING = "⚠️ Ваша подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ."

PREM_EXPIRY_WARNING = "⚠️ Ваша Premium-подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ."

SUB_EXPIRED = "❌ Ваша подписка истекла! Профиль VPN был удален. Продлите подписку, чтобы создать новый."

TRIBUTE_CANCELLED = "ℹ️ Подписка Tribute отменена. Доступ сохраняется до окончания оплаченного периода."


# ── Dynamic ───────────────────────────────────────────────────────────────────

def welcome(bot_name: str) -> str:
    return (
        f"Добро пожаловать в VPN бота `{bot_name}`!\n"
        "Вам предоставлен **бесплатный** тестовый период на **3 дня**!\n\n"
        "Узнайте больше о видах подписки в разделе ℹ️ Помощь!\n\n"
        "А если коротко, то Premium вам нужен для обхода БС, когда не работает ничего кроме ВК, Max..."
    )


def payment_success(action_type: str, months: int, suffix: str, tier_label: str) -> str:
    return (
        f"✅ Оплата прошла успешно! Ваша подписка {action_type} на {months} {suffix}.\n"
        f"Тариф: {tier_label}\n\n"
        "Спасибо за покупку! 🎉"
    )


def admin_payment_notification(
    action_type: str, full_name: str, telegram_id: int,
    months: int, suffix: str, tier_label: str, final_price: int,
) -> str:
    return (
        f"{action_type.capitalize()} подписка пользователем "
        f"`{full_name}` | `{telegram_id}` "
        f"на {months} {suffix} ({tier_label}) — {final_price}₽"
    )


def admin_menu_text(total: int, with_sub: int, without_sub: int, online_count: int) -> str:
    return (
        "**Административное меню**\n\n"
        f"**Всего пользователей**: `{total}`\n"
        f"**С подпиской/Без подписки**: `{with_sub}`/`{without_sub}`\n"
        f"**Онлайн**: `{online_count}` | **Офлайн**: `{with_sub - online_count}`"
    )


def broadcast_result(success: int, failed: int, total: int) -> str:
    return (
        f"📨 Результаты рассылки:\n\n"
        f"• Успешно: {success}\n"
        f"• Не удалось: {failed}\n"
        f"• Всего: {total}"
    )


def network_stats_text(upload: str, upload_size: str, download: str, download_size: str) -> str:
    return (
        "📊 **Статистика использования сети:**\n\n"
        f"🔼 Upload - `{upload} {upload_size}` | 🔽 Download - `{download} {download_size}`"
    )


def fix_profiles_result(fixed_db_count: int, success_count: int, fail_count: int, users_len: int) -> str:
    return (
        f"🔧 **Исправление профилей завершено:**\n\n"
        f"📊 Исправлено дат в БД: `{fixed_db_count}`\n"
        f"✅ Обновлено профилей в 3x-ui: `{success_count}`\n"
        f"❌ Ошибок обновления: `{fail_count}`\n\n"
        f"📋 Всего проверено пользователей: `{users_len}`"
    )


def check_subs_result(stats: dict) -> str:
    if "error" in stats:
        return f"❌ **Ошибка при проверке подписок:**\n\n📋 {stats['error']}"

    text = (
        f"🔍 **Проверка подписок завершена:**\n\n"
        f"📊 **Статистика:**\n"
        f"• Всего клиентов в 3x-ui: `{stats['total_3xui']}`\n"
        f"• Всего пользователей в БД: `{stats['total_db']}`\n"
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
            text += f"... и ещё {len(problems) - 10} проблем\n\n"

    fixed = [d for d in stats['details'] if d['status'] == 'fixed']
    if fixed:
        text += f"✅ **Исправлено ({len(fixed)}):**\n\n"
        for i, fix in enumerate(fixed[:5], 1):
            text += f"{i}. `{fix['email']}`\n"
        if len(fixed) > 5:
            text += f"... и ещё {len(fixed) - 5}\n\n"

    return text


def delete_user_confirm(
    full_name: str, username: str, telegram_id: int,
    reg_date: str, sub_end: str, has_profile: bool,
) -> str:
    return (
        f"⚠️ **Подтвердите удаление:**\n\n"
        f"👤 **Имя:** `{full_name}`\n"
        f"📱 **Username:** `{username}`\n"
        f"🆔 **Telegram ID:** `{telegram_id}`\n"
        f"📅 **Регистрация:** `{reg_date}`\n"
        f"⏰ **Подписка до:** `{sub_end}`\n"
        f"🔧 **Профиль:** `{'Есть' if has_profile else 'Нет'}`\n\n"
        f"❗️ **Это действие необратимо!**"
    )


def delete_user_success(telegram_id: int) -> str:
    return (
        f"✅ **Пользователь удалён**\n\n"
        f"🆔 Telegram ID: `{telegram_id}`\n\n"
        "Профили в 3x-ui также были удалены (если существовали)."
    )


def delete_user_failure(telegram_id: int) -> str:
    return (
        f"❌ **Ошибка удаления**\n\n"
        f"🆔 Telegram ID: `{telegram_id}`\n\n"
        "Пользователь не найден в базе данных."
    )


def tribute_sub_activated(action: str, tier_label: str, months: int, suffix: str) -> str:
    return (
        f"✅ Подписка {action} через Tribute!\n"
        f"Тариф: {tier_label} | Срок: {months} {suffix}\n\n"
        "Используйте /connect для получения конфигурации."
    )


def tribute_admin_notify(action: str, telegram_id: int, months: int, suffix: str, tier_label: str) -> str:
    return (
        f"Tribute: подписка {action} — `{telegram_id}` "
        f"на {months} {suffix} ({tier_label})"
    )


def tribute_digital_activated(product_name: str, tier_label: str, hours: int) -> str:
    return (
        f"✅ Подписка активирована через Tribute!\n"
        f"Товар: {product_name} | Тариф: {tier_label} | Срок: {hours}ч\n\n"
        "Используйте /connect для получения конфигурации."
    )


def tribute_digital_admin_notify(telegram_id: int, product_name: str, tier_label: str, hours: int) -> str:
    return (
        f"Tribute: цифровой товар — `{telegram_id}` "
        f"«{product_name}» ({tier_label}, {hours}ч)"
    )
