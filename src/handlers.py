import asyncio
import logging
import json
import io
import qrcode
from datetime import datetime, timedelta
from aiogram import Dispatcher, Router, F, Bot
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from database import (
    StaticProfile, get_user, create_user, update_subscription,
    get_all_users, create_static_profile, get_static_profiles,
    User, Session, get_user_stats as db_user_stats, delete_user,
    fix_all_subscription_dates, get_users_with_profiles,
)
from functions import (
    create_vless_profile, create_profile, inbound_id_from_profile,
    delete_client_by_email, generate_vless_url,
    get_user_stats, create_static_client, get_global_stats,
    get_online_users, generate_sub_url, update_client_expiry,
    get_safe_expiry_timestamp, force_update_profile_expiry,
    check_and_fix_subscriptions, safe_json_loads,
)

logger = logging.getLogger(__name__)

router = Router()

MAX_MESSAGE_LENGTH = 4096

TIER_LABELS = {
    "basic": "📦 Basic",
    "premium": "⭐ Premium",
}

class AdminStates(StatesGroup):
    ADD_TIME = State()
    REMOVE_TIME = State()
    CREATE_STATIC_PROFILE = State()
    SEND_MESSAGE = State()
    ADD_TIME_USER = State()
    REMOVE_TIME_USER = State()
    ADD_TIME_AMOUNT = State()
    REMOVE_TIME_AMOUNT = State()
    SEND_MESSAGE_TARGET = State()
    DELETE_USER = State()

def split_text(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list:
    if len(text) <= max_length:
        return [text]
    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break
        part = text[:max_length]
        last_newline = part.rfind('\n')
        if last_newline != -1:
            part = part[:last_newline]
        parts.append(part)
        text = text[len(part):].lstrip()
    return parts


# ────────────────────────────────────────────────────────────
# Вспомогательные функции
# ────────────────────────────────────────────────────────────

def _get_profiles_dict(user) -> dict:
    """Возвращает все профили пользователя как dict {inbound_id_str: profile_data}.
    Прозрачно поддерживает legacy vless_profile_data."""
    if user.profiles_data:
        return safe_json_loads(user.profiles_data, default={})
    # Legacy fallback
    if user.vless_profile_data:
        pdata = safe_json_loads(user.vless_profile_data, default={})
        if pdata:
            return {str(config.INBOUND_ID): pdata}
    return {}


def _get_sub_id(user) -> str | None:
    """Возвращает sub_id пользователя (он одинаков у всех инбаундов)."""
    profiles = _get_profiles_dict(user)
    if profiles:
        first = next(iter(profiles.values()))
        return first.get("sub_id")
    return None


def _has_profiles(user) -> bool:
    return bool(_get_profiles_dict(user))


async def _create_profiles_for_tier(telegram_id: int, subscription_end, tier: str) -> dict:
    """Создаёт профили во всех инбаундах тарифа.
    Возвращает dict {inbound_id_str: profile_data}."""
    expiry_time = get_safe_expiry_timestamp(subscription_end)
    inbound_configs = config.get_inbound_configs(tier)
    new_profiles: dict = {}
    for cfg in inbound_configs:
        pdata = await create_profile(telegram_id, expiry_time, cfg)
        if pdata:
            new_profiles[str(cfg["id"])] = pdata
        else:
            logger.error(f"🛑 Failed to create profile for inbound {cfg['id']}, user {telegram_id}")
    return new_profiles


async def _update_all_profiles_expiry(profiles: dict, subscription_end) -> None:
    """Обновляет expiry во всех инбаундах пользователя."""
    expiry_time = get_safe_expiry_timestamp(subscription_end)
    for inbound_id_str, pdata in profiles.items():
        email = pdata.get("email")
        if email:
            try:
                await update_client_expiry(email, expiry_time, int(inbound_id_str))
            except Exception as e:
                logger.error(f"🛑 Failed to update expiry for {email} in inbound {inbound_id_str}: {e}")


async def _delete_extra_profiles(telegram_id: int, current_profiles: dict, new_inbound_ids: set) -> dict:
    """Удаляет профили из инбаундов, которых нет в новом тарифе.
    Возвращает обновлённый dict профилей."""
    to_keep = {}
    for inbound_id_str, pdata in current_profiles.items():
        if int(inbound_id_str) in new_inbound_ids:
            to_keep[inbound_id_str] = pdata
        else:
            email = pdata.get("email")
            if email:
                try:
                    await delete_client_by_email(email, int(inbound_id_str))
                    logger.info(f"✅ Removed extra profile {email} from inbound {inbound_id_str} (tier downgrade)")
                except Exception as e:
                    logger.error(f"🛑 Error removing extra profile {email}: {e}")
    return to_keep


async def show_menu(bot: Bot, chat_id: int, message_id: int = None):
    """Отображение главного меню."""
    user = await get_user(chat_id)
    if not user:
        return

    status = "Активна" if user.subscription_end > datetime.utcnow() else "Истекла"
    expire_date = user.subscription_end.strftime("%d-%m-%Y %H:%M") if status == "Активна" else status
    tier = getattr(user, 'subscription_tier', 'basic') or 'basic'
    tier_label = TIER_LABELS.get(tier, tier)

    text = (
        f"**Имя профиля**: `{user.full_name}`\n"
        f"**Id**: `{user.telegram_id}`\n"
        f"**Подписка**: `{status}` ({tier_label})\n"
        f"**Дата окончания подписки**: `{expire_date}`"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Продлить" if status == "Активна" else "💵 Оплатить", callback_data="renew_sub")
    builder.button(text="✅ Подключить", callback_data="connect")
    builder.button(text="📊 Статистика", callback_data="stats")
    builder.button(text="ℹ️ Помощь", callback_data="help")

    if user.is_admin:
        builder.button(text="⚠️ Админ. меню", callback_data="admin_menu")

    builder.adjust(2, 2, 1)

    if message_id:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text,
            reply_markup=builder.as_markup(), parse_mode='Markdown'
        )
    else:
        await bot.send_message(
            chat_id=chat_id, text=text,
            reply_markup=builder.as_markup(), parse_mode='Markdown'
        )


# ────────────────────────────────────────────────────────────
# Команды пользователя
# ────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def start_cmd(message: Message, bot: Bot):
    logger.info(f"ℹ️  Start command from {message.from_user.id}")
    user = await get_user(message.from_user.id)

    update_data = {}
    if user:
        if user.full_name != message.from_user.full_name:
            update_data["full_name"] = message.from_user.full_name
        if user.username != message.from_user.username:
            update_data["username"] = message.from_user.username
    else:
        is_admin = message.from_user.id in config.ADMINS
        user = await create_user(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
            is_admin=is_admin
        )
        await message.answer(
            f"Добро пожаловать в VPN бота `{(await bot.get_me()).full_name}`!\n"
            "Вам предоставлен **бесплатный** тестовый период на **3 дня**!",
            parse_mode='Markdown'
        )
        await asyncio.sleep(2)

    if update_data:
        with Session() as session:
            db_user = session.query(User).get(user.id)
            for key, value in update_data.items():
                setattr(db_user, key, value)
            session.commit()

    await show_menu(bot, message.from_user.id)


@router.message(Command("menu"))
async def menu_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        await start_cmd(message, bot)
        return

    update_data = {}
    if user.full_name != message.from_user.full_name:
        update_data["full_name"] = message.from_user.full_name
    if user.username != message.from_user.username:
        update_data["username"] = message.from_user.username

    if update_data:
        with Session() as session:
            db_user = session.query(User).get(user.id)
            for key, value in update_data.items():
                setattr(db_user, key, value)
            session.commit()

    await show_menu(bot, message.from_user.id)


@router.message(Command("renew"))
async def renew_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        await start_cmd(message, bot)
        return
    await message.answer(
        "💵 **Выберите тариф и период подписки:**",
        reply_markup=_build_renew_keyboard(),
        parse_mode='Markdown'
    )


def _build_renew_keyboard():
    """Строит клавиатуру выбора тарифа и периода."""
    builder = InlineKeyboardBuilder()
    has_premium = config.has_premium_inbounds()

    # Секция Basic
    builder.button(text="─── 📦 Basic ───", callback_data="noop")
    builder.adjust(1)
    for months in sorted(config.PRICES.keys()):
        price = config.calculate_price(months, "basic")
        price_info = config.PRICES[months]
        discount_text = f" (-{price_info['discount_percent']}%)" if price_info["discount_percent"] > 0 else ""
        builder.button(text=f"{months} мес. — {price} руб.{discount_text}", callback_data=f"pay_basic_{months}")

    if has_premium:
        builder.button(text="─── ⭐ Premium ───", callback_data="noop")
        for months in sorted(config.PRICES.keys()):
            price = config.calculate_price(months, "premium")
            price_info = config.PRICES[months]
            discount_text = f" (-{price_info['discount_percent']}%)" if price_info["discount_percent"] > 0 else ""
            builder.button(text=f"{months} мес. — {price} руб.{discount_text}", callback_data=f"pay_premium_{months}")

    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("connect"))
async def connect_cmd(message: Message, bot: Bot):
    """Команда /connect."""
    user = await get_user(message.from_user.id)
    if not user:
        await start_cmd(message, bot)
        return

    if user.subscription_end < datetime.utcnow():
        await message.answer("⚠️ Подписка истекла! Продлите подписку.")
        return

    tier = getattr(user, 'subscription_tier', 'basic') or 'basic'

    if not _has_profiles(user):
        await message.answer("⚙️ Создаём ваш VPN профиль...")
        new_profiles = await _create_profiles_for_tier(user.telegram_id, user.subscription_end, tier)
        if new_profiles:
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                if db_user:
                    db_user.profiles_data = json.dumps(new_profiles)
                    session.commit()
            user = await get_user(user.telegram_id)
        else:
            await message.answer("🛑 Ошибка при создании профиля. Попробуйте позже.")
            return

    profiles = _get_profiles_dict(user)
    if not profiles:
        await message.answer("⚠️ У вас пока нет созданного профиля.")
        return

    sub_id = _get_sub_id(user)
    await _send_profile_message(message, user, profiles, sub_id, edit=False)


@router.message(Command("stats"))
async def stats_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user or not _has_profiles(user):
        await message.answer("⚠️ Профиль не создан")
        return

    await message.answer("⚙️ Загружаем вашу статистику...")
    profiles = _get_profiles_dict(user)
    first_profile = next(iter(profiles.values()))
    stats = await get_user_stats(first_profile["email"])

    upload = f"{stats.get('upload', 0) / 1024 / 1024:.2f}"
    upload_size = 'MB' if int(float(upload)) < 1024 else 'GB'
    if upload_size == "GB":
        upload = f"{int(float(upload) / 1024):.2f}"

    download = f"{stats.get('download', 0) / 1024 / 1024:.2f}"
    download_size = 'MB' if int(float(download)) < 1024 else 'GB'
    if download_size == "GB":
        download = f"{int(float(download) / 1024):.2f}"

    text = (
        "📊 **Ваша статистика:**\n\n"
        f"🔼 Загружено: `{upload} {upload_size}`\n"
        f"🔽 Скачано: `{download} {download_size}`\n"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    await message.answer(text, parse_mode='Markdown', reply_markup=builder.as_markup())


@router.message(Command("help"))
async def help_cmd(message: Message, bot: Bot):
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    text = "О боте:\n"
    await message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())


# ────────────────────────────────────────────────────────────
# Callback-обработчики пользователя
# ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "help")
async def help_msg(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    text = "О боте:\n"
    await callback.message.edit_text(text, parse_mode='HTML', reply_markup=builder.as_markup())


@router.callback_query(F.data == "renew_sub")
async def renew_subscription(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "💵 **Выберите тариф и период подписки:**",
        reply_markup=_build_renew_keyboard(),
        parse_mode='Markdown'
    )


@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    """Заглушка для декоративных кнопок-заголовков."""
    await callback.answer()


@router.callback_query(F.data.startswith("pay_"))
async def process_payment(callback: CallbackQuery, bot: Bot):
    """Обработчик нажатия кнопки оплаты.
    Формат callback_data: pay_{tier}_{months} или (legacy) pay_{months}.
    """
    await callback.answer()
    try:
        parts = callback.data.split("_")
        # pay_basic_3  → parts = ["pay", "basic", "3"]
        # pay_1 (legacy) → parts = ["pay", "1"]
        if len(parts) == 3:
            tier = parts[1]   # "basic" | "premium"
            months = int(parts[2])
        else:
            tier = "basic"
            months = int(parts[1])

        if months not in config.PRICES:
            await callback.message.answer("❌ Неверный период подписки")
            return

        final_price = config.calculate_price(months, tier)
        tier_label = TIER_LABELS.get(tier, tier)
        suffix = "месяц" if months == 1 else "месяца" if months in (2, 3, 4) else "месяцев"

        prices = [LabeledPrice(label=f"VPN {tier_label} на {months} мес.", amount=final_price * 100)]
        if config.PAYMENT_TOKEN:
            await bot.send_invoice(
                chat_id=callback.from_user.id,
                title=f"VPN {tier_label} на {months} {suffix}",
                description=f"Доступ к VPN сервису на {months} {suffix}",
                payload=f"subscription_{tier}_{months}",
                provider_token=config.PAYMENT_TOKEN,
                currency="RUB",
                prices=prices,
                start_parameter="create_subscription",
                need_email=True,
                need_phone_number=False
            )
        else:
            await callback.message.answer("❌ Оплата временно недоступна")
    except Exception as e:
        logger.error(f"🛑 Payment error: {e}")
        await callback.message.answer("❌ Ошибка при создании счета на оплату")


@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    try:
        payload = message.successful_payment.invoice_payload

        # Поддержка форматов:
        #   subscription_basic_3   (новый)
        #   subscription_3         (legacy)
        if payload.startswith("subscription_"):
            remainder = payload[len("subscription_"):]
            parts = remainder.split("_")
            if len(parts) == 2 and parts[0] in ("basic", "premium"):
                tier, months = parts[0], int(parts[1])
            else:
                tier, months = "basic", int(parts[0])
        else:
            await message.answer("❌ Ошибка: неверный формат платежа")
            return

        final_price = config.calculate_price(months, tier)
        tier_label = TIER_LABELS.get(tier, tier)

        user = await get_user(message.from_user.id)
        if not user:
            await message.answer("❌ Ошибка: пользователь не найден")
            return

        now = datetime.utcnow()
        action_type = "продлена" if user.subscription_end > now else "куплена"

        # Обновляем подписку и тариф в БД
        success = await update_subscription(message.from_user.id, months, tier=tier)
        suffix = "месяц" if months == 1 else "месяца" if months in (2, 3, 4) else "месяцев"

        if success:
            updated_user = await get_user(message.from_user.id)
            inbound_configs = config.get_inbound_configs(tier)
            new_inbound_ids = {cfg["id"] for cfg in inbound_configs}

            # Берём текущие профили
            current_profiles = _get_profiles_dict(updated_user)

            # 1) Удаляем лишние профили при даунгрейде/смене тарифа
            current_profiles = await _delete_extra_profiles(
                message.from_user.id, current_profiles, new_inbound_ids
            )

            # 2) Обновляем expiry в существующих профилях / создаём недостающие
            for cfg in inbound_configs:
                iid_str = str(cfg["id"])
                if iid_str in current_profiles:
                    # Профиль уже есть — обновляем expiry
                    pdata = current_profiles[iid_str]
                    email = pdata.get("email")
                    if email:
                        expiry_time = get_safe_expiry_timestamp(updated_user.subscription_end)
                        await update_client_expiry(email, expiry_time, cfg["id"])
                else:
                    # Профиля нет — создаём
                    expiry_time = get_safe_expiry_timestamp(updated_user.subscription_end)
                    pdata = await create_profile(message.from_user.id, expiry_time, cfg)
                    if pdata:
                        current_profiles[iid_str] = pdata

            # 3) Сохраняем обновлённые профили
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
                if db_user:
                    db_user.profiles_data = json.dumps(current_profiles)
                    db_user.subscription_tier = tier
                    session.commit()

            await message.answer(
                f"✅ Оплата прошла успешно! Ваша подписка {action_type} на {months} {suffix}.\n"
                f"Тариф: {tier_label}\n\n"
                "Спасибо за покупку! 🎉"
            )

            admin_message = (
                f"{action_type.capitalize()} подписка пользователем "
                f"`{user.full_name}` | `{user.telegram_id}` "
                f"на {months} {suffix} ({tier_label}) — {final_price}₽"
            )
            for admin_id in config.ADMINS:
                try:
                    await bot.send_message(admin_id, admin_message, parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"🛑 Failed to send notification to admin {admin_id}: {e}")
        else:
            await message.answer("❌ Ошибка при обновлении подписки")
    except Exception as e:
        logger.error(f"🛑 Successful payment processing error: {e}")
        await message.answer("❌ Ошибка при обработке платежа")


@router.callback_query(F.data == "connect")
async def connect_profile(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("🛑 Ошибка профиля")
        return

    if user.subscription_end < datetime.utcnow():
        await callback.answer("⚠️ Подписка истекла! Продлите подписку.")
        return

    tier = getattr(user, 'subscription_tier', 'basic') or 'basic'

    if not _has_profiles(user):
        await callback.message.edit_text("⚙️ Создаём ваш VPN профиль...")
        expiry_time = get_safe_expiry_timestamp(user.subscription_end)
        new_profiles = await _create_profiles_for_tier(user.telegram_id, user.subscription_end, tier)
        if new_profiles:
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                if db_user:
                    db_user.profiles_data = json.dumps(new_profiles)
                    session.commit()
            user = await get_user(user.telegram_id)
        else:
            await callback.message.answer("🛑 Ошибка при создании профиля. Попробуйте позже.")
            return

    profiles = _get_profiles_dict(user)
    if not profiles:
        await callback.message.answer("⚠️ У вас пока нет созданного профиля.")
        return

    # Проверяем и синхронизируем expiry в 3x-ui
    expiry_time = get_safe_expiry_timestamp(user.subscription_end)
    if expiry_time > 0:
        await _update_all_profiles_expiry(profiles, user.subscription_end)

    sub_id = _get_sub_id(user)
    await _send_profile_message(callback.message, user, profiles, sub_id, edit=True, delete_after=True)


async def _send_profile_message(msg_or_callback, user, profiles: dict, sub_id: str, edit: bool = False, delete_after: bool = False):
    """Отправляет или редактирует сообщение с QR-кодом профиля.
    Всегда один QR-код на sub_id (3x-ui агрегирует все конфиги по sub_id).
    """
    sub_url = generate_sub_url(sub_id) if sub_id else ""

    # Формируем текст с raw VLESS ссылками
    profile_lines = []
    for inbound_id_str, pdata in profiles.items():
        vless_url = generate_vless_url(pdata)
        protocol = pdata.get('security', 'reality')
        label = "🔒 Reality" if protocol == "reality" else "⚡ xhttp"
        profile_lines.append(f"{label}:\n`{vless_url}`")

    instructions = (
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

    # QR-код кодирует subscription URL
    qr_data = "https://" + sub_url if sub_url else (generate_vless_url(next(iter(profiles.values()))))
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    photo = BufferedInputFile(img_byte_arr.getvalue(), filename="qr.png")

    builder = InlineKeyboardBuilder()
    if sub_url:
        builder.button(text='Подключиться', url='https://' + sub_url)
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    builder.adjust(1)

    caption = instructions
    if profile_lines:
        caption += "\n" + "\n\n".join(profile_lines)

    if delete_after:
        try:
            await msg_or_callback.delete()
        except Exception:
            pass
    await msg_or_callback.answer_photo(
        photo=photo,
        caption=caption[:1024],  # Telegram лимит caption
        reply_markup=builder.as_markup(),
        parse_mode='Markdown'
    )


@router.callback_query(F.data == "stats")
async def user_stats(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user or not _has_profiles(user):
        await callback.answer("⚠️ Профиль не создан")
        return

    await callback.message.edit_text("⚙️ Загружаем вашу статистику...")
    profiles = _get_profiles_dict(user)
    first_profile = next(iter(profiles.values()))
    stats = await get_user_stats(first_profile["email"])

    upload = f"{stats.get('upload', 0) / 1024 / 1024:.2f}"
    upload_size = 'MB' if int(float(upload)) < 1024 else 'GB'
    if upload_size == "GB":
        upload = f"{int(float(upload) / 1024):.2f}"

    download = f"{stats.get('download', 0) / 1024 / 1024:.2f}"
    download_size = 'MB' if int(float(download)) < 1024 else 'GB'
    if download_size == "GB":
        download = f"{int(float(download) / 1024):.2f}"

    await callback.message.delete()
    text = (
        "📊 **Ваша статистика:**\n\n"
        f"🔼 Загружено: `{upload} {upload_size}`\n"
        f"🔽 Скачано: `{download} {download_size}`\n"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    await callback.message.answer(text, parse_mode='Markdown', reply_markup=builder.as_markup())


# ────────────────────────────────────────────────────────────
# Админ-панель
# ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user or not user.is_admin:
        await callback.answer("🛑 Доступ запрещен!")
        return

    total, with_sub, without_sub = await db_user_stats()
    online_count = await get_online_users()

    text = (
        "**Административное меню**\n\n"
        f"**Всего пользователей**: `{total}`\n"
        f"**С подпиской/Без подписки**: `{with_sub}`/`{without_sub}`\n"
        f"**Онлайн**: `{online_count}` | **Офлайн**: `{with_sub - online_count}`"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="+ время", callback_data="admin_add_time")
    builder.button(text="- время", callback_data="admin_remove_time")
    builder.button(text="📋 Список пользователей", callback_data="admin_user_list")
    builder.button(text="🗑️ Удалить пользователя", callback_data="admin_delete_user")
    builder.button(text="🔍 Проверить подписки", callback_data="admin_check_subscriptions")
    builder.button(text="📊 Статистика исп. сети", callback_data="admin_network_stats")
    builder.button(text="🔧 Исправить профили", callback_data="admin_fix_profiles")
    builder.button(text="📢 Рассылка", callback_data="admin_send_message")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(2, 1, 1, 1, 1, 1, 1, 1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')


@router.callback_query(F.data == "admin_add_time")
async def admin_add_time_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите Telegram ID пользователя:")
    await state.set_state(AdminStates.ADD_TIME_USER)


@router.message(AdminStates.ADD_TIME_USER)
async def admin_add_time_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("Введите количество времени в формате:\nМесяцы Дни Часы Минуты\nПример: 1 0 0 0")
        await state.set_state(AdminStates.ADD_TIME_AMOUNT)
    except ValueError:
        await message.answer("Ошибка: ID должен быть числом")


@router.message(AdminStates.ADD_TIME_AMOUNT)
async def admin_add_time_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['user_id']
    parts = message.text.split()

    if len(parts) != 4:
        await message.answer("Ошибка: нужно ввести 4 числа")
        return

    try:
        months, days, hours, minutes = map(int, parts)
        total_seconds = (
            months * 30 * 24 * 60 * 60 +
            days * 24 * 60 * 60 +
            hours * 60 * 60 +
            minutes * 60
        )

        with Session() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                if user.subscription_end > datetime.utcnow():
                    user.subscription_end += timedelta(seconds=total_seconds)
                else:
                    user.subscription_end = datetime.utcnow() + timedelta(seconds=total_seconds)
                session.commit()

                # Обновляем expiry во всех инбаундах
                profiles = _get_profiles_dict(user)
                if profiles:
                    try:
                        await _update_all_profiles_expiry(profiles, user.subscription_end)
                        logger.info(f"✅ Updated expiry in all inbounds for user {user_id} (admin add time)")
                    except Exception as e:
                        logger.error(f"🛑 Failed to update expiry for user {user_id}: {e}")

                await message.answer(f"✅ Добавлено время пользователю {user_id}")
            else:
                await message.answer("❌ Пользователь не найден")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        await state.clear()


@router.callback_query(F.data == "admin_remove_time")
async def admin_remove_time_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите Telegram ID пользователя:")
    await state.set_state(AdminStates.REMOVE_TIME_USER)


@router.message(AdminStates.REMOVE_TIME_USER)
async def admin_remove_time_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("Введите количество времени в формате:\nМесяцы Дни Часы Минуты\nПример: 1 0 0 0")
        await state.set_state(AdminStates.REMOVE_TIME_AMOUNT)
    except ValueError:
        await message.answer("Ошибка: ID должен быть числом")


@router.message(AdminStates.REMOVE_TIME_AMOUNT)
async def admin_remove_time_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['user_id']
    parts = message.text.split()

    if len(parts) != 4:
        await message.answer("Ошибка: нужно ввести 4 числа")
        return

    try:
        months, days, hours, minutes = map(int, parts)
        total_seconds = (
            months * 30 * 24 * 60 * 60 +
            days * 24 * 60 * 60 +
            hours * 60 * 60 +
            minutes * 60
        )

        with Session() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                new_end = user.subscription_end - timedelta(seconds=total_seconds)
                if new_end < datetime.utcnow():
                    new_end = datetime.utcnow()
                user.subscription_end = new_end
                session.commit()

                # Обновляем expiry во всех инбаундах
                profiles = _get_profiles_dict(user)
                if profiles:
                    try:
                        await _update_all_profiles_expiry(profiles, user.subscription_end)
                        logger.info(f"✅ Updated expiry in all inbounds for user {user_id} (admin remove time)")
                    except Exception as e:
                        logger.error(f"🛑 Failed to update expiry for user {user_id}: {e}")

                await message.answer(f"✅ Удалено время у пользователя {user_id}")
            else:
                await message.answer("❌ Пользователь не найден")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        await state.clear()


@router.callback_query(F.data == "admin_user_list")
async def admin_user_list(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ С подпиской", callback_data="user_list_active")
    builder.button(text="🛑 Без подписки", callback_data="user_list_inactive")
    builder.button(text="⏱️ Статические профили", callback_data="static_profiles_menu")
    builder.button(text="⬅️ Назад", callback_data="admin_menu")
    builder.adjust(1, 1, 1)
    await callback.message.edit_text("**Выберите фильтр**", reply_markup=builder.as_markup(), parse_mode='Markdown')


@router.callback_query(F.data == "user_list_active")
async def handle_user_list_active(callback: CallbackQuery):
    users = await get_all_users(with_subscription=True)
    await callback.answer()
    if not users:
        await callback.answer("Нет пользователей с активной подпиской")
        return

    text = "👤 <b>Пользователи с активной подпиской:</b>\n\n"
    for user in users:
        expire_date = user.subscription_end.strftime("%d.%m.%Y %H:%M")
        username = f"@{user.username}" if user.username else "none"
        tier = getattr(user, 'subscription_tier', 'basic') or 'basic'
        user_line = f"• {user.full_name} ({username} | <code>{user.telegram_id}</code>) [{tier}] — до <code>{expire_date}</code>\n"
        if len(text) + len(user_line) > MAX_MESSAGE_LENGTH:
            await callback.message.answer(text, parse_mode="HTML")
            text = "👤 <b>Продолжение:</b>\n\n"
        text += user_line
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "user_list_inactive")
async def handle_user_list_inactive(callback: CallbackQuery):
    await callback.answer()
    users = await get_all_users(with_subscription=False)
    if not users:
        await callback.answer("Нет пользователей без подписки")
        return

    text = "👤 <b>Пользователи без подписки:</b>\n\n"
    for user in users:
        username = f"@{user.username}" if user.username else "none"
        user_line = f"• {user.full_name} ({username} | <code>{user.telegram_id}</code>)\n"
        if len(text) + len(user_line) > MAX_MESSAGE_LENGTH:
            await callback.message.answer(text, parse_mode="HTML")
            text = "👤 <b>Продолжение:</b>\n\n"
        text += user_line
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "admin_send_message")
async def admin_send_message_start(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ С подпиской", callback_data="target_active")
    builder.button(text="🛑 Без подписки", callback_data="target_inactive")
    builder.button(text="👥 Всем пользователям", callback_data="target_all")
    builder.button(text="↩️ Назад", callback_data="admin_menu")
    builder.adjust(1)
    await callback.message.edit_text("Выберите целевую аудиторию:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("target_"))
async def admin_send_message_target(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    target = callback.data.split("_")[1]
    await state.update_data(target=target)
    await callback.message.answer("Введите сообщение для рассылки:")
    await state.set_state(AdminStates.SEND_MESSAGE)


@router.message(AdminStates.SEND_MESSAGE)
async def admin_send_message(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    target = data['target']
    text = message.text

    if target == "active":
        users = await get_all_users(with_subscription=True)
    elif target == "inactive":
        users = await get_all_users(with_subscription=False)
    else:
        users = await get_all_users()

    success = failed = 0
    for user in users:
        try:
            await bot.send_message(user.telegram_id, text)
            success += 1
        except Exception as e:
            logger.error(f"🛑 Ошибка отправки {user.telegram_id}: {e}")
            failed += 1

    await message.answer(
        f"📨 Результаты рассылки:\n\n"
        f"• Успешно: {success}\n"
        f"• Не удалось: {failed}\n"
        f"• Всего: {len(users)}"
    )
    await state.clear()


@router.callback_query(F.data == "static_profiles_menu")
async def static_profiles_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🆕 Добавить статический профиль", callback_data="static_profile_add")
    builder.button(text="📋 Вывести статические профили", callback_data="static_profile_list")
    builder.button(text="⬅️ Назад", callback_data="admin_user_list")
    builder.adjust(1)
    await callback.message.edit_text("**Выберите действие**", reply_markup=builder.as_markup(), parse_mode='Markdown')


@router.callback_query(F.data == "static_profile_add")
async def static_profile_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите имя для статического профиля:")
    await state.set_state(AdminStates.CREATE_STATIC_PROFILE)


@router.message(AdminStates.CREATE_STATIC_PROFILE)
async def process_static_profile_name(message: Message, state: FSMContext):
    profile_name = message.text
    profile_data = await create_static_client(profile_name)

    if profile_data:
        vless_url = generate_vless_url(profile_data)
        sub_id = profile_data.get("sub_id")
        sub_url = generate_sub_url(sub_id) if sub_id else vless_url

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(sub_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        photo = BufferedInputFile(img_byte_arr.getvalue(), filename="qr.png")

        await create_static_profile(profile_name, sub_url)
        profiles = await get_static_profiles()
        static_id = next((p.id for p in profiles if p.name == profile_name), None)
        builder = InlineKeyboardBuilder()
        if static_id:
            builder.button(text="🗑️ Удалить", callback_data=f"delete_static_{static_id}")
        await message.answer_photo(
            photo=photo,
            caption=f"Профиль создан!\n\n`{sub_url}`",
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
    else:
        await message.answer("Ошибка при создании профиля")

    await state.clear()


@router.callback_query(F.data == "static_profile_list")
async def static_profile_list(callback: CallbackQuery):
    profiles = await get_static_profiles()
    if not profiles:
        await callback.answer("Нет статических профилей")
        return

    for profile in profiles:
        builder = InlineKeyboardBuilder()
        builder.button(text="🗑️ Удалить", callback_data=f"delete_static_{profile.id}")
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(profile.vless_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        photo = BufferedInputFile(img_byte_arr.getvalue(), filename="qr.png")
        await callback.message.answer_photo(
            photo=photo,
            caption=f"**{profile.name}**\n`{profile.vless_url}`",
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )


@router.callback_query(F.data.startswith("delete_static_"))
async def handle_delete_static_profile(callback: CallbackQuery):
    try:
        profile_id = int(callback.data.split("_")[-1])
        with Session() as session:
            profile = session.query(StaticProfile).filter_by(id=profile_id).first()
            if not profile:
                await callback.answer("⚠️ Профиль не найден")
                return
            await delete_client_by_email(profile.name)
            session.delete(profile)
            session.commit()
        await callback.answer("✅ Профиль удален!")
        await callback.message.delete()
    except Exception as e:
        logger.error(f"🛑 Ошибка при удалении статического профиля: {e}")
        await callback.answer("⚠️ Ошибка при удалении профиля")


@router.callback_query(F.data == "admin_network_stats")
async def network_stats(callback: CallbackQuery):
    stats = await get_global_stats()
    upload = f"{stats.get('upload', 0) / 1024 / 1024:.2f}"
    upload_size = 'MB' if int(float(upload)) < 1024 else 'GB'
    if upload_size == "GB":
        upload = f"{int(float(upload) / 1024):.2f}"
    download = f"{stats.get('download', 0) / 1024 / 1024:.2f}"
    download_size = 'MB' if int(float(download)) < 1024 else 'GB'
    if download_size == "GB":
        download = f"{int(float(download) / 1024):.2f}"
    await callback.answer()
    text = (
        "📊 **Статистика использования сети:**\n\n"
        f"🔼 Upload - `{upload} {upload_size}` | 🔽 Download - `{download} {download_size}`"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin_menu")
    await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin_fix_profiles")
async def admin_fix_profiles(callback: CallbackQuery):
    """Исправляет все профили с неправильными датами."""
    await callback.answer("⏳ Исправляем профили...")
    try:
        fixed_db_count = await fix_all_subscription_dates()
        users = await get_users_with_profiles()

        success_count = fail_count = 0
        for user in users:
            profiles = _get_profiles_dict(user)
            for inbound_id_str, pdata in profiles.items():
                email = pdata.get("email")
                if email:
                    try:
                        result = await force_update_profile_expiry(email, user.subscription_end, int(inbound_id_str))
                        if result:
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        logger.error(f"🛑 Error fixing profile {email}: {e}")
                        fail_count += 1

        text = (
            f"🔧 **Исправление профилей завершено:**\n\n"
            f"📊 Исправлено дат в БД: `{fixed_db_count}`\n"
            f"✅ Обновлено профилей в 3x-ui: `{success_count}`\n"
            f"❌ Ошибок обновления: `{fail_count}`\n\n"
            f"📋 Всего проверено пользователей: `{len(users)}`"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="admin_menu")
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"🛑 Error in admin_fix_profiles: {e}")
        await callback.message.answer(f"❌ Ошибка при исправлении профилей: {str(e)}")


@router.callback_query(F.data == "admin_check_subscriptions")
async def admin_check_subscriptions(callback: CallbackQuery):
    """Проверяет и исправляет расхождения между 3x-ui и базой данных."""
    await callback.answer("⏳ Проверяем подписки...")
    try:
        stats = await check_and_fix_subscriptions()

        if "error" in stats:
            text = f"❌ **Ошибка при проверке подписок:**\n\n📋 {stats['error']}"
        else:
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

            problems = [d for d in stats['details'] if d['status'] in ['mismatch', 'fix_failed', 'fix_error']]
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

        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="admin_menu")
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"🛑 Error in admin_check_subscriptions: {e}")
        await callback.message.answer(f"❌ Ошибка при проверке подписок: {str(e)}")


@router.callback_query(F.data == "admin_delete_user")
async def admin_delete_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "🗑️ **Удаление пользователя**\n\nВведите Telegram ID пользователя для удаления:",
        parse_mode='Markdown'
    )
    await state.set_state(AdminStates.DELETE_USER)


@router.message(AdminStates.DELETE_USER)
async def admin_delete_user_process(message: Message, state: FSMContext):
    try:
        telegram_id = int(message.text)
        user = await get_user(telegram_id)

        if not user:
            await message.answer(f"❌ Пользователь с Telegram ID `{telegram_id}` не найден")
            await state.clear()
            return

        username = f"@{user.username}" if user.username else "отсутствует"
        has_profile = _has_profiles(user)
        text = (
            f"⚠️ **Подтвердите удаление:**\n\n"
            f"👤 **Имя:** `{user.full_name}`\n"
            f"📱 **Username:** `{username}`\n"
            f"🆔 **Telegram ID:** `{user.telegram_id}`\n"
            f"📅 **Регистрация:** `{user.registration_date.strftime('%d-%m-%Y %H:%M')}`\n"
            f"⏰ **Подписка до:** `{user.subscription_end.strftime('%d-%m-%Y %H:%M')}`\n"
            f"🔧 **Профиль:** `{'Есть' if has_profile else 'Нет'}`\n\n"
            f"❗️ **Это действие необратимо!**"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Подтвердить удаление", callback_data=f"confirm_delete_{telegram_id}")
        builder.button(text="❌ Отмена", callback_data="admin_menu")
        builder.adjust(1)
        await message.answer(text, parse_mode='Markdown', reply_markup=builder.as_markup())
        await state.clear()
    except ValueError:
        await message.answer("❌ Ошибка: Telegram ID должен быть числом")
    except Exception as e:
        logger.error(f"🛑 Error in admin_delete_user_process: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()


@router.callback_query(F.data.startswith("confirm_delete_"))
async def admin_confirm_delete_user(callback: CallbackQuery):
    await callback.answer()
    try:
        telegram_id = int(callback.data.split("_")[2])
        result = await delete_user(telegram_id)

        if result:
            text = (
                f"✅ **Пользователь удалён**\n\n"
                f"🆔 Telegram ID: `{telegram_id}`\n\n"
                f"Профили в 3x-ui также были удалены (если существовали)."
            )
        else:
            text = (
                f"❌ **Ошибка удаления**\n\n"
                f"🆔 Telegram ID: `{telegram_id}`\n\n"
                f"Пользователь не найден в базе данных."
            )
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ В админ-меню", callback_data="admin_menu")
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"🛑 Error in admin_confirm_delete_user: {e}")
        await callback.message.answer(f"❌ Ошибка при удалении: {str(e)}")


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    if callback.message.photo:
        await callback.message.delete()
        await show_menu(bot, callback.from_user.id)
    else:
        await show_menu(bot, callback.from_user.id, callback.message.message_id)


def setup_handlers(dp: Dispatcher):
    dp.include_router(router)
    logger.info("✅ Handlers setup completed")
