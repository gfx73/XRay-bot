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
from database import Session, User, init_db, get_all_users, delete_user_profile

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
                # Уведомление за 1 день до окончания
                if (user.subscription_end - now < timedelta(days=1)
                        and user.subscription_end >= now
                        and not user.notified):
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

                # Удаление истёкших профилей из 3x-ui
                if user.subscription_end <= now:
                    deleted_any = False

                    if user.profiles_data:
                        try:
                            profile = json.loads(user.profiles_data)
                            email = profile.get("email")
                            if email:
                                try:
                                    success = await delete_client_by_email(email)
                                    if success:
                                        logger.info(f"✅ Deleted expired client {email}")
                                    else:
                                        logger.warning(f"⚠️ Failed to delete {email}")
                                    deleted_any = True
                                except Exception as e:
                                    logger.warning(f"⚠️ Deletion error for {email}: {e}")
                        except Exception as e:
                            logger.warning(f"⚠️ Error parsing profiles_data for user {user.telegram_id}: {e}")

                    if deleted_any:
                        await delete_user_profile(user.telegram_id)
                        try:
                            await bot.send_message(
                                user.telegram_id,
                                "❌ Ваша подписка истекла! Профиль VPN был удален. Продлите подписку, чтобы создать новый."
                            )
                        except Exception as e:
                            logger.warning(f"⚠️ Notification error: {e}")

        except Exception as e:
            logger.warning(f"⚠️ Subscription check error: {e}")

        await asyncio.sleep(3600)

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
                    is_admin=True,
                    subscription_end=datetime.now() + timedelta(days=365)
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

    tasks = [
        dp.start_polling(bot),
        check_subscriptions(bot),
    ]

    if config.TRIBUTE_API_KEY:
        from tribute_webhook import create_tribute_app
        tribute_app = create_tribute_app(bot)
        server = uvicorn.Server(uvicorn.Config(
            tribute_app,
            host="0.0.0.0",
            port=config.TRIBUTE_WEBHOOK_PORT,
            log_level="warning",
        ))
        tasks.append(server.serve())
        logger.info(f"ℹ️  Tribute webhook listening on port {config.TRIBUTE_WEBHOOK_PORT}")
    else:
        logger.info("ℹ️  TRIBUTE_API_KEY not set — Tribute webhook disabled")

    logger.info("ℹ️  Starting bot...")
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.error(f"❌ Bot start error: {e}")
        return

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopping bot...")
        exit(0)
    except Exception as e:
        logger.error(f"❌ Main loop error: {e}")
        exit(1)
