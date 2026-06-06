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
    create_client,
    delete_client_by_email,
    update_client_expiry,
    get_safe_expiry_timestamp,
    safe_json_loads,
)

logger = logging.getLogger(__name__)

PERIOD_TO_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "yearly": 12,
}


async def _sync_profiles(telegram_id: int, tier: str, bot: Bot) -> None:
    """Создаёт/обновляет VPN-клиентов в 3x-ui после активации Tribute-подписки."""
    updated_user = await get_user(telegram_id)
    if not updated_user:
        return

    expiry_time = get_safe_expiry_timestamp(updated_user.subscription_end)
    existing = safe_json_loads(updated_user.profiles_data, default={})
    if not isinstance(existing, dict) or "standard" not in existing:
        existing = {}

    profiles_to_save = {}

    # Standard-клиент (Reality, безлимит) — всегда присутствует
    if "standard" in existing:
        await update_client_expiry(existing["standard"]["email"], expiry_time)
        profiles_to_save["standard"] = existing["standard"]
    else:
        basic_cfgs = config.get_inbound_configs("basic")
        new_std = await create_client(telegram_id, expiry_time, basic_cfgs)
        if new_std:
            profiles_to_save["standard"] = new_std

    # WL-клиент (xhttp/CDN, с лимитом) — только для premium
    if tier == "premium" and config.has_premium_inbounds():
        if "wl" in existing:
            await update_client_expiry(existing["wl"]["email"], expiry_time)
            profiles_to_save["wl"] = existing["wl"]
        else:
            premium_cfgs = config.get_inbound_configs("premium")
            new_wl = await create_client(
                telegram_id, expiry_time, premium_cfgs,
                email_suffix="_wl",
                traffic_limit_gb=config.PREMIUM_TRAFFIC_LIMIT_GB,
            )
            if new_wl:
                profiles_to_save["wl"] = new_wl
    elif "wl" in existing:
        # Даунгрейд с premium — удаляем wl-клиента
        await delete_client_by_email(existing["wl"]["email"])

    with Session() as session:
        db_user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if db_user:
            db_user.profiles_data = json.dumps(profiles_to_save)
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
