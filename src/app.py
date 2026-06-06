import json
import asyncio
import logging
import warnings
import coloredlogs
import uvicorn
from config import config
from aiogram import Bot, Dispatcher
from aiogram.types import PreCheckoutQuery
from handlers import setup_handlers
from datetime import datetime, timedelta
from functions import delete_client_by_email
from database import Session, User, init_db, get_all_users, delete_user_profile, validate_and_fix_subscription_date

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


async def _check_user_subscription(bot, user, now: datetime):
    std_active = bool(user.subscription_end and user.subscription_end > now)
    prem_active = bool(getattr(user, 'premium_end', None) and user.premium_end > now)

    # Уведомление за 1 день до окончания standard
    if std_active and (user.subscription_end - now < timedelta(days=1)) and not user.notified:
        try:
            await bot.send_message(
                user.telegram_id,
                "⚠️ Ваша подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ."
            )
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                if db_user:
                    db_user.notified = True
                    session.commit()
        except Exception as e:
            logger.warning(f"⚠️ Notification error: {e}")

    # Уведомление за 1 день до окончания premium
    if prem_active and (user.premium_end - now < timedelta(days=1)) and not user.premium_notified:
        try:
            await bot.send_message(
                user.telegram_id,
                "⚠️ Ваша Premium-подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ."
            )
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                if db_user:
                    db_user.premium_notified = True
                    session.commit()
        except Exception as e:
            logger.warning(f"⚠️ Notification error: {e}")

    if not user.profiles_data:
        return

    try:
        profiles = json.loads(user.profiles_data)
    except Exception:
        return

    if not isinstance(profiles, dict):
        return

    changed = False

    # Удаление истёкшего standard профиля
    if not std_active and "standard" in profiles:
        std_profile = profiles.get("standard", {})
        email = std_profile.get("email") if isinstance(std_profile, dict) else None
        if email:
            try:
                success = await delete_client_by_email(email)
                if success:
                    logger.info(f"✅ Deleted expired standard client {email}")
                else:
                    logger.warning(f"⚠️ Failed to delete {email}")
            except Exception as e:
                logger.warning(f"⚠️ Deletion error for {email}: {e}")
        del profiles["standard"]
        changed = True

    # Удаление истёкшего wl (premium) профиля
    if not prem_active and "wl" in profiles:
        wl_profile = profiles.get("wl", {})
        email = wl_profile.get("email") if isinstance(wl_profile, dict) else None
        if email:
            try:
                success = await delete_client_by_email(email)
                if success:
                    logger.info(f"✅ Deleted expired wl client {email}")
                else:
                    logger.warning(f"⚠️ Failed to delete {email}")
            except Exception as e:
                logger.warning(f"⚠️ Deletion error for {email}: {e}")
        del profiles["wl"]
        changed = True

    if changed:
        with Session() as session:
            db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
            if db_user:
                db_user.subscription_tier = "premium" if prem_active else "basic"
                db_user.profiles_data = json.dumps(profiles) if profiles else None
                session.commit()

        if not std_active and not prem_active:
            try:
                await bot.send_message(
                    user.telegram_id,
                    "❌ Ваша подписка истекла! Профиль VPN был удален. Продлите подписку, чтобы создать новый."
                )
            except Exception as e:
                logger.warning(f"⚠️ Notification error: {e}")

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
                    subscription_tier=config.TRIAL_TIER,
                )
                session.add(new_admin)
        session.commit()
    logger.info("✅ Admin status updated in database")

async def setup_bot_commands(bot: Bot):
    """Регистрация команд бота в меню Telegram."""
    from aiogram.types import BotCommand
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
        logger.info("✅ Handlers registered")
    except Exception as e:
        logger.error(f"❌ Handler registration error: {e}")
        return

    @dp.pre_checkout_query()
    async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    server = None
    other_tasks = [asyncio.create_task(check_subscriptions(bot))]

    if config.TRIBUTE_API_KEY:
        from tribute_webhook import create_tribute_app
        tribute_app = create_tribute_app(bot)
        server = uvicorn.Server(uvicorn.Config(
            tribute_app,
            host="127.0.0.1",
            port=config.TRIBUTE_WEBHOOK_PORT,
            log_level="warning",
        ))
        other_tasks.append(asyncio.create_task(server.serve()))
        logger.info(f"ℹ️  Tribute webhook listening on port {config.TRIBUTE_WEBHOOK_PORT}")
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
        exit(1)
