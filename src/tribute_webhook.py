import hmac
import hashlib
import json
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from fastapi import FastAPI, Request, HTTPException

from config import config
from database import Session, User, get_user, create_user, update_subscription
from functions import (
    create_profile,
    delete_client_by_email,
    update_client_expiry,
    get_safe_expiry_timestamp,
)
from handlers import _get_profiles_dict, _delete_extra_profiles

logger = logging.getLogger(__name__)

PERIOD_TO_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "yearly": 12,
}


async def _sync_profiles(telegram_id: int, tier: str, bot: Bot) -> None:
    """Создаёт/обновляет/удаляет профили в 3x-ui после активации Tribute-подписки.
    Повторяет логику process_successful_payment из handlers.py."""
    updated_user = await get_user(telegram_id)
    if not updated_user:
        return

    inbound_configs = config.get_inbound_configs(tier)
    new_inbound_ids = {cfg["id"] for cfg in inbound_configs}

    current_profiles = _get_profiles_dict(updated_user)
    current_profiles = await _delete_extra_profiles(telegram_id, current_profiles, new_inbound_ids)

    expiry_time = get_safe_expiry_timestamp(updated_user.subscription_end)
    for cfg in inbound_configs:
        iid_str = str(cfg["id"])
        if iid_str in current_profiles:
            email = current_profiles[iid_str].get("email")
            if email:
                await update_client_expiry(email, expiry_time, cfg["id"])
        else:
            pdata = await create_profile(telegram_id, expiry_time, cfg)
            if pdata:
                current_profiles[iid_str] = pdata

    with Session() as session:
        db_user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if db_user:
            db_user.profiles_data = json.dumps(current_profiles)
            db_user.subscription_tier = tier
            session.commit()


def _resolve_tier(subscription_name: str) -> str:
    if subscription_name == config.TRIBUTE_PREMIUM_PLAN_NAME:
        return "premium"
    return "basic"


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
            raise HTTPException(status_code=400, detail="Invalid JSON")

        event_name = data.get("name", "")
        payload = data.get("payload", {})
        telegram_id: int | None = payload.get("telegram_user_id")

        if not telegram_id:
            logger.warning(f"⚠️ Tribute webhook '{event_name}': no telegram_user_id")
            return {"ok": True}

        if event_name in ("newSubscription", "renewedSubscription"):
            tier = _resolve_tier(payload.get("subscription_name", ""))
            months = PERIOD_TO_MONTHS.get(payload.get("period", "monthly"), 1)
            tier_label = "⭐ Premium" if tier == "premium" else "📦 Basic"
            suffix = _months_suffix(months)

            # Создаём запись если пользователь ещё не запускал бота
            user = await get_user(telegram_id)
            if not user:
                username = payload.get("telegram_username")
                await create_user(telegram_id, str(telegram_id), username=username)
                logger.info(f"✅ Tribute: auto-created user {telegram_id}")

            success = await update_subscription(telegram_id, months, tier=tier)
            if success:
                try:
                    await _sync_profiles(telegram_id, tier, bot)
                except Exception as e:
                    logger.error(f"🛑 Tribute: profile sync error for {telegram_id}: {e}")

                action = "продлена" if event_name == "renewedSubscription" else "активирована"
                try:
                    await bot.send_message(
                        telegram_id,
                        f"✅ Подписка {action} через Tribute!\n"
                        f"Тариф: {tier_label} | Срок: {months} {suffix}\n\n"
                        "Используйте /connect для получения конфигурации."
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Tribute: failed to notify user {telegram_id}: {e}")

                for admin_id in config.ADMINS:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"Tribute: подписка {action} — `{telegram_id}` "
                            f"на {months} {suffix} ({tier_label})",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass

                logger.info(f"✅ Tribute '{event_name}': user {telegram_id}, tier={tier}, months={months}")
            else:
                logger.error(f"🛑 Tribute: update_subscription failed for {telegram_id}")

        elif event_name == "cancelledSubscription":
            # Подписка действует до expires_at — check_subscriptions удалит профили при истечении
            logger.info(f"ℹ️ Tribute 'cancelledSubscription': user {telegram_id} — will expire naturally")
            try:
                await bot.send_message(
                    telegram_id,
                    "ℹ️ Подписка Tribute отменена. Доступ сохраняется до окончания оплаченного периода."
                )
            except Exception:
                pass

        else:
            logger.debug(f"ℹ️ Tribute: ignoring event '{event_name}'")

        return {"ok": True}

    return app
