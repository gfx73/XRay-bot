import asyncio
import logging
import os
import secrets
import sys
import warnings
from datetime import datetime, timedelta

import coloredlogs
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BufferedInputFile, PreCheckoutQuery

from config import config
from database import (
    Session,
    User,
    engine,
    get_all_users,
    init_db,
    validate_and_fix_subscription_date,
)
from functions import delete_client_by_email
from handlers import ThrottlingMiddleware, setup_handlers
from messages import SUB_EXPIRED, SUB_EXPIRY_WARNING
from models import SlotName, UserProfiles
from tribute_webhook import create_tribute_app

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Настройка логирования
coloredlogs.install(level='info')
logger = logging.getLogger(__name__)

async def check_subscriptions(bot: Bot):
    """Проверка статуса подписок."""
    while True:
        try:
            now = datetime.utcnow()
            users = await get_all_users()

            for user in users:
                try:
                    await _check_user_subscription(bot, user, now)
                except Exception as e:
                    logger.warning(f"⚠️ Subscription check error for user {user.telegram_id}: {e}")

        except Exception as e:
            logger.warning(f"⚠️ Subscription check error: {e}")

        await asyncio.sleep(3600)


async def _send_expiry_notifications(bot, user, now: datetime, active: bool):
    """Send 24h expiry warning notification."""
    if active and (user.subscription_end - now < timedelta(days=1)) and not user.notified:
        try:
            await bot.send_message(user.telegram_id, SUB_EXPIRY_WARNING, parse_mode="Markdown")
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                if db_user:
                    db_user.notified = True
                    session.commit()
        except Exception as e:
            logger.warning(f"⚠️ Notification error: {e}")


async def _delete_profile_slot(profiles: UserProfiles, slot: SlotName) -> UserProfiles:
    """Delete one expired VPN slot and return updated profiles."""
    profile = profiles.standard if slot == SlotName.STANDARD else profiles.wl
    if profile is not None:
        try:
            success = await delete_client_by_email(profile.email)
            if success:
                logger.info(f"✅ Deleted expired {slot.value} client {profile.email}")
            else:
                logger.warning(f"⚠️ Failed to delete {profile.email}")
        except Exception as e:
            logger.warning(f"⚠️ Deletion error for {profile.email}: {e}")
    if slot == SlotName.STANDARD:
        profiles.standard = None
    else:
        profiles.wl = None
    return profiles


async def _check_user_subscription(bot, user, now: datetime):
    active = bool(user.subscription_end and user.subscription_end > now)

    await _send_expiry_notifications(bot, user, now, active)

    profiles = user.profiles
    if not profiles:
        return
    changed = False

    if not active and profiles.standard is not None:
        profiles = await _delete_profile_slot(profiles, SlotName.STANDARD)
        changed = True

    if not active and profiles.wl is not None:
        profiles = await _delete_profile_slot(profiles, SlotName.WL)
        changed = True

    if changed:
        with Session() as session:
            db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
            if db_user:
                db_user.profiles = profiles if profiles else UserProfiles()
                session.commit()

        if not active:
            try:
                await bot.send_message(user.telegram_id, SUB_EXPIRED, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"⚠️ Notification error: {e}")

async def send_regular_backup(bot: Bot):
    """Регулярно отправляет бэкап БД всем администраторам."""
    while True:
        await asyncio.sleep(21600)
        try:
            db_path = os.path.abspath(engine.url.database)
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            filename = f"users_{date_str}.db"
            with open(db_path, "rb") as f:
                data = f.read()
            doc = BufferedInputFile(data, filename=filename)
            for admin_id in config.ADMINS:
                try:
                    await bot.send_document(
                        admin_id,
                        doc,
                        caption=f"💾 Ежедневный бэкап БД ({date_str})"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send backup to admin {admin_id}: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Daily backup error: {e}")


async def update_admins_status():
    """Обновляет статус администраторов в базе данных."""
    with Session() as session:
        session.query(User).update({User.is_admin: False})
        for admin_id in config.ADMINS:
            user = session.query(User).filter_by(telegram_id=admin_id).first()
            if user:
                user.is_admin = True
            else:
                new_admin = User(
                    telegram_id=admin_id,
                    full_name=f"Admin {admin_id}",
                    username=None,
                    is_admin=True,
                    subscription_end=validate_and_fix_subscription_date(
                        datetime.utcnow() + timedelta(days=config.TRIAL_DAYS)
                    ),
                    referral_code=secrets.token_urlsafe(8),
                )
                session.add(new_admin)
        session.commit()
    logger.info("✅ Admin status updated in database")

async def setup_bot_commands(bot: Bot):
    """Регистрация команд бота в меню Telegram."""
    commands = [
        BotCommand(command="start", description="🚀 Запуск бота"),
        BotCommand(command="menu", description="📋 Главное меню"),
        BotCommand(command="renew", description="💵 Продлить подписку"),
        BotCommand(command="connect", description="✅ Подключить VPN"),
        BotCommand(command="stats", description="📊 Статистика"),
        BotCommand(command="help", description="ℹ️ Справка"),
    ]
    try:
        await bot.set_my_commands(commands)
        logger.info("✅ Bot commands registered successfully")
    except Exception as e:
        logger.error(f"❌ Failed to register bot commands: {e}")

async def main():
    if config.PAYMENT_TOKEN:
        raise RuntimeError(
            "PAYMENT_TOKEN настроен, но Telegram Payments не интегрирован "
            "с реферальной системой. Добавьте вызов _reward_referrer в "
            "process_successful_payment (handlers.py) и удалите этот guard."
        )

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    try:
        await init_db()
        logger.info("✅ Database initialized")
        await update_admins_status()
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        return

    try:
        await setup_bot_commands(bot)
    except Exception as e:
        logger.error(f"❌ Bot commands setup error: {e}")

    try:
        setup_handlers(dp)
        throttle = ThrottlingMiddleware()
        dp.message.middleware(throttle)
        dp.callback_query.middleware(throttle)
        logger.info("✅ Handlers registered")
    except Exception as e:
        logger.error(f"❌ Handler registration error: {e}")
        return

    @dp.pre_checkout_query()
    async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    server = None
    other_tasks = [
        asyncio.create_task(check_subscriptions(bot)),
        asyncio.create_task(send_regular_backup(bot)),
    ]

    if config.TRIBUTE_API_KEY:
        tribute_app = create_tribute_app(bot)
        server = uvicorn.Server(uvicorn.Config(
            tribute_app,
            host="127.0.0.1",
            port=config.TRIBUTE_WEBHOOK_PORT,
            log_level="warning",
        ))
        other_tasks.append(asyncio.create_task(server.serve()))
        logger.info(f"ℹ️  Tribute webhook listening on port {config.TRIBUTE_WEBHOOK_PORT}")
        if config.TRIBUTE_DIGITAL_PRODUCTS:
            for p in config.TRIBUTE_DIGITAL_PRODUCTS:
                logger.info(f"ℹ️  Tribute digital product: '{p.name}' → {p.hours}h")
        else:
            logger.info("ℹ️  No Tribute digital products configured")
    else:
        logger.info("ℹ️  TRIBUTE_API_KEY not set — Tribute webhook disabled")

    logger.info("ℹ️  Starting bot...")
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("👋 Shutting down...")
        if server:
            server.should_exit = True
        for task in other_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*other_tasks, return_exceptions=True)
        await bot.session.close()
        logger.info("✅ Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"❌ Main loop error: {e}")
        sys.exit(1)
