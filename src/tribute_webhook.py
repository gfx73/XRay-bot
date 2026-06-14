import contextlib
import hashlib
import hmac
import json
import logging

from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request

from config import DigitalProduct, TributeSub, config
from database import Session, User, create_user, get_user, update_subscription
from functions import (
    get_safe_expiry_timestamp,
    sync_profiles,
)
from messages import (
    TRIBUTE_CANCELLED,
    referral_reward_received,
    tribute_admin_notify,
    tribute_digital_activated,
    tribute_digital_admin_notify,
    tribute_sub_activated,
)

logger = logging.getLogger(__name__)

PERIOD_TO_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "yearly": 12,
}


async def _sync_profiles_after_payment(telegram_id: int, is_first_purchase: bool = False, wl_traffic_gb: int | None = None) -> None:
    """Создаёт/обновляет VPN-клиентов в 3x-ui после активации Tribute-подписки.

    is_first_purchase: если True — обновляет лимит трафика WL-профиля до полного и ставит has_purchased.
    wl_traffic_gb: явное значение лимита трафика (используется при реферальном бонусе).
    """
    updated_user = await get_user(telegram_id)
    if not updated_user:
        return

    expiry = get_safe_expiry_timestamp(updated_user.subscription_end)
    existing = updated_user.profiles

    profiles_to_save = await sync_profiles(telegram_id, expiry, existing, is_first_purchase=is_first_purchase, wl_traffic_gb=wl_traffic_gb)

    with Session() as session:
        db_user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if db_user:
            db_user.profiles = profiles_to_save
            if is_first_purchase:
                db_user.has_purchased = True
            session.commit()


def _find_subscription(name: str) -> TributeSub | None:
    for sub in config.TRIBUTE_SUBSCRIPTIONS:
        if sub.name == name:
            return sub
    return None


def _find_digital_product(name: str) -> DigitalProduct | None:
    for product in config.TRIBUTE_DIGITAL_PRODUCTS:
        if product.name == name:
            return product
    return None


async def _reward_referrer(buyer_id: int, reward_hours: int, bot: Bot) -> None:
    if reward_hours <= 0:
        return
    buyer = await get_user(buyer_id)
    if not buyer or not buyer.referred_by:
        return
    referrer_id = buyer.referred_by
    success = await update_subscription(referrer_id, hours=reward_hours)
    if not success:
        logger.warning(f"⚠️ Referral reward: update_subscription failed for referrer {referrer_id}")
        return
    logger.info(f"✅ Referral reward: {reward_hours}h → referrer {referrer_id} (buyer {buyer_id})")

    referrer = await get_user(referrer_id)
    if referrer:
        wl_traffic = None
        if (
            not referrer.has_purchased
            and config.has_wl_inbounds()
            and config.TRIAL_WL_TRAFFIC_LIMIT_GB > 0
            and config.WL_TRAFFIC_LIMIT_GB > 0
        ):
            wl_traffic = config.WL_TRAFFIC_LIMIT_GB
        with contextlib.suppress(Exception):
            await _sync_profiles_after_payment(referrer_id, wl_traffic_gb=wl_traffic)

    with contextlib.suppress(Exception):
        await bot.send_message(
            referrer_id,
            referral_reward_received(reward_hours),
            parse_mode="Markdown",
        )


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
    sub = _find_subscription(payload.get("subscription_name", ""))
    months = PERIOD_TO_MONTHS.get(payload.get("period", "monthly"), 1)
    suffix = _months_suffix(months)

    await _ensure_user(telegram_id, payload)

    user = await get_user(telegram_id)
    is_first_purchase = not bool(user and user.has_purchased)

    success = await update_subscription(telegram_id, months=months)
    if not success:
        logger.error(f"🛑 Tribute: update_subscription failed for {telegram_id}")
        return

    try:
        await _sync_profiles_after_payment(telegram_id, is_first_purchase=is_first_purchase)
    except Exception as e:
        logger.error(f"🛑 Tribute: profile sync error for {telegram_id}: {e}")

    action = "продлена" if event_name == "renewed_subscription" else "активирована"
    with contextlib.suppress(Exception):
        await bot.send_message(telegram_id, tribute_sub_activated(action, months, suffix))

    for admin_id in config.ADMINS:
        with contextlib.suppress(Exception):
            await bot.send_message(
                admin_id,
                tribute_admin_notify(action, telegram_id, months, suffix),
                parse_mode="Markdown",
            )

    await _reward_referrer(telegram_id, sub.referral_reward_hours if sub else 0, bot)
    logger.info(f"✅ Tribute '{event_name}': user {telegram_id}, months={months}")


async def _handle_digital_product_event(
    product: DigitalProduct, payload: dict, telegram_id: int, bot: Bot
) -> None:
    """Handle new_digital_product events for a matched product."""
    await _ensure_user(telegram_id, payload)

    user = await get_user(telegram_id)
    is_first_purchase = not bool(user and user.has_purchased)

    success = await update_subscription(telegram_id, hours=product.hours)
    if not success:
        logger.error(f"🛑 Tribute: update_subscription failed for {telegram_id} (product='{product.name}')")
        return

    try:
        await _sync_profiles_after_payment(telegram_id, is_first_purchase=is_first_purchase)
    except Exception as e:
        logger.error(f"🛑 Tribute: profile sync error for {telegram_id}: {e}")

    with contextlib.suppress(Exception):
        await bot.send_message(telegram_id, tribute_digital_activated(product.name, product.hours))

    for admin_id in config.ADMINS:
        with contextlib.suppress(Exception):
            await bot.send_message(
                admin_id,
                tribute_digital_admin_notify(telegram_id, product.name, product.hours),
                parse_mode="Markdown",
            )

    await _reward_referrer(telegram_id, product.referral_reward_hours, bot)
    logger.info(f"✅ Tribute 'new_digital_product': user {telegram_id}, product='{product.name}', hours={product.hours}")


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
            logger.info(f"ℹ️ Tribute 'cancelled_subscription': user {telegram_id} — will expire naturally")
            with contextlib.suppress(Exception):
                await bot.send_message(telegram_id, TRIBUTE_CANCELLED, parse_mode="Markdown")
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
