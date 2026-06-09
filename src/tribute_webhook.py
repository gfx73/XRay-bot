import contextlib
import hashlib
import hmac
import json
import logging

from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request

from config import DigitalProduct, config
from database import Session, User, create_user, get_user, update_subscription
from functions import (
    get_safe_expiry_timestamp,
    sync_profiles_for_tier,
)
from models import SubscriptionTier

logger = logging.getLogger(__name__)

PERIOD_TO_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "yearly": 12,
}


async def _sync_profiles(telegram_id: int, tier: SubscriptionTier) -> None:
    """Создаёт/обновляет VPN-клиентов в 3x-ui после активации Tribute-подписки."""
    updated_user = await get_user(telegram_id)
    if not updated_user:
        return

    std_expiry = get_safe_expiry_timestamp(updated_user.subscription_end)
    prem_expiry = get_safe_expiry_timestamp(getattr(updated_user, 'premium_end', None))
    existing = updated_user.profiles

    profiles_to_save = await sync_profiles_for_tier(telegram_id, tier, std_expiry, prem_expiry, existing)

    with Session() as session:
        db_user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if db_user:
            db_user.profiles = profiles_to_save
            session.commit()


def _resolve_tier(subscription_name: str) -> SubscriptionTier:
    if subscription_name == config.TRIBUTE_PREMIUM_PLAN_NAME:
        return SubscriptionTier.PREMIUM
    return SubscriptionTier.STANDARD


def _find_digital_product(name: str) -> DigitalProduct | None:
    for product in config.TRIBUTE_DIGITAL_PRODUCTS:
        if product.name == name:
            return product
    return None


def _verify_signature(body: bytes, signature: str) -> bool:
    if not config.TRIBUTE_API_KEY:
        return False
    expected = hmac.new(config.TRIBUTE_API_KEY.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _months_suffix(months: int) -> str:
    if months == 1:
        return "месяц"
    if months in (2, 3, 4):
        return "месяца"
    return "месяцев"


async def _ensure_user(telegram_id: int, payload: dict) -> None:
    user = await get_user(telegram_id)
    if not user:
        username = payload.get("telegram_username")
        await create_user(telegram_id, str(telegram_id), username=username)
        logger.info(f"✅ Tribute: auto-created user {telegram_id}")


async def _handle_subscription_event(
    event_name: str, payload: dict, telegram_id: int, bot: Bot
) -> None:
    """Handle new_subscription and renewed_subscription events."""
    tier = _resolve_tier(payload.get("subscription_name", ""))
    months = PERIOD_TO_MONTHS.get(payload.get("period", "monthly"), 1)
    tier_label = "⭐ Premium" if tier == SubscriptionTier.PREMIUM else "📦 Standard"
    suffix = _months_suffix(months)

    await _ensure_user(telegram_id, payload)

    success = await update_subscription(telegram_id, months=months, tier=tier)
    if not success:
        logger.error(f"🛑 Tribute: update_subscription failed for {telegram_id}")
        return

    try:
        await _sync_profiles(telegram_id, tier)
    except Exception as e:
        logger.error(f"🛑 Tribute: profile sync error for {telegram_id}: {e}")

    action = "продлена" if event_name == "renewed_subscription" else "активирована"
    with contextlib.suppress(Exception):
        await bot.send_message(
            telegram_id,
            f"✅ Подписка {action} через Tribute!\n"
            f"Тариф: {tier_label} | Срок: {months} {suffix}\n\n"
            "Используйте /connect для получения конфигурации."
        )

    for admin_id in config.ADMINS:
        with contextlib.suppress(Exception):
            await bot.send_message(
                admin_id,
                f"Tribute: подписка {action} — `{telegram_id}` "
                f"на {months} {suffix} ({tier_label})",
                parse_mode="Markdown",
            )

    logger.info(f"✅ Tribute '{event_name}': user {telegram_id}, tier={tier}, months={months}")


async def _handle_digital_product_event(
    product: DigitalProduct, payload: dict, telegram_id: int, bot: Bot
) -> None:
    """Handle new_digital_product events for a matched product."""
    tier = product.tier
    tier_label = "⭐ Premium" if tier == SubscriptionTier.PREMIUM else "📦 Standard"

    await _ensure_user(telegram_id, payload)

    success = await update_subscription(telegram_id, hours=product.hours, tier=tier)
    if not success:
        logger.error(f"🛑 Tribute: update_subscription failed for {telegram_id} (product='{product.name}')")
        return

    try:
        await _sync_profiles(telegram_id, tier)
    except Exception as e:
        logger.error(f"🛑 Tribute: profile sync error for {telegram_id}: {e}")

    with contextlib.suppress(Exception):
        await bot.send_message(
            telegram_id,
            f"✅ Подписка активирована через Tribute!\n"
            f"Товар: {product.name} | Тариф: {tier_label} | Срок: {product.hours}ч\n\n"
            "Используйте /connect для получения конфигурации."
        )

    for admin_id in config.ADMINS:
        with contextlib.suppress(Exception):
            await bot.send_message(
                admin_id,
                f"Tribute: цифровой товар — `{telegram_id}` "
                f"«{product.name}» ({tier_label}, {product.hours}ч)",
                parse_mode="Markdown",
            )

    logger.info(f"✅ Tribute 'new_digital_product': user {telegram_id}, product='{product.name}', "
                f"tier={tier}, hours={product.hours}")


def create_tribute_app(bot: Bot) -> FastAPI:
    app = FastAPI(title="Tribute Webhook")

    @app.post("/tribute/webhook")
    async def tribute_webhook(request: Request):
        body = await request.body()
        signature = request.headers.get("trbt-signature", "")

        if not _verify_signature(body, signature):
            logger.warning("⚠️ Tribute webhook: invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        try:
            data = json.loads(body)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON") from None

        logger.info("Tribute webhook received")
        logger.info(data)

        event_name = data.get("name", "")
        payload = data.get("payload", {})
        telegram_id: int | None = payload.get("telegram_user_id")

        if not telegram_id:
            logger.warning(f"⚠️ Tribute webhook '{event_name}': no telegram_user_id")
            return {"ok": True}

        if event_name in ("new_subscription", "renewed_subscription"):
            await _handle_subscription_event(event_name, payload, telegram_id, bot)
        elif event_name == "cancelled_subscription":
            # Подписка действует до expires_at — check_subscriptions удалит профили при истечении
            logger.info(f"ℹ️ Tribute 'cancelled_subscription': user {telegram_id} — will expire naturally")
            with contextlib.suppress(Exception):
                await bot.send_message(
                    telegram_id,
                    "ℹ️ Подписка Tribute отменена. Доступ сохраняется до окончания оплаченного периода."
                )
        elif event_name == "new_digital_product":
            product_name = payload.get("name") or payload.get("product_name", "")
            product = _find_digital_product(product_name)
            if product:
                await _handle_digital_product_event(product, payload, telegram_id, bot)
            else:
                logger.info(f"ℹ️ Tribute 'new_digital_product': unrecognized product '{product_name}'")
        else:
            logger.info(f"ℹ️ Tribute: ignoring event '{event_name}'")

        return {"ok": True}

    return app
