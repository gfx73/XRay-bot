from config import config

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
import logging
import json

logger = logging.getLogger(__name__)

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    full_name = Column(String)
    username = Column(String)
    registration_date = Column(DateTime, default=datetime.utcnow)
    subscription_end = Column(DateTime)
    is_admin = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)
    # ── Новые поля ──────────────────────────────────────────
    subscription_tier = Column(String, default="basic")   # "basic" | "premium"
    profiles_data = Column(Text, nullable=True)            # JSON: {inbound_id: profile_data}

class StaticProfile(Base):
    __tablename__ = 'static_profiles'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    vless_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

engine = create_engine('sqlite:///users.db', echo=False)
Session = sessionmaker(bind=engine)

async def init_db():
    Base.metadata.create_all(engine)
    logger.info("✅ Database tables created")

async def get_user(telegram_id: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            original_end = user.subscription_end
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            if user.subscription_end != original_end:
                session.commit()
                logger.info(f"✅ Fixed subscription date for user {telegram_id}: {original_end} -> {user.subscription_end}")
        return user

async def create_user(telegram_id: int, full_name: str, username: str = None, is_admin: bool = False):
    with Session() as session:
        subscription_end = validate_and_fix_subscription_date(
            datetime.utcnow() + timedelta(days=config.TRIAL_DAYS)
        )
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            subscription_end=subscription_end,
            is_admin=is_admin,
            subscription_tier=config.TRIAL_TIER,
        )
        session.add(user)
        session.commit()
        logger.info(f"✅ New user created: {telegram_id} with subscription_end: {subscription_end}")
        return user

async def delete_user_profile(telegram_id: int):
    """Очищает данные профилей пользователя."""
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            user.profiles_data = None
            user.notified = False
            session.commit()
            logger.info(f"✅ User profile deleted: {telegram_id}")

async def update_subscription(telegram_id: int, months: int, tier: str = None):
    """Обновляет подписку с учётом текущего состояния.

    Args:
        tier: если передан — обновляет subscription_tier пользователя.
    """
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            now = datetime.utcnow()
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            if user.subscription_end > now:
                user.subscription_end += timedelta(days=months * 30)
            else:
                user.subscription_end = now + timedelta(days=months * 30)
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            user.notified = False
            if tier is not None:
                user.subscription_tier = tier
            session.commit()
            logger.info(f"✅ Subscription updated for {telegram_id}: +{months} months, tier={tier}, new end: {user.subscription_end}")
            return True
        return False

async def get_all_users(with_subscription: bool = None):
    with Session() as session:
        query = session.query(User)
        if with_subscription is not None:
            if with_subscription:
                query = query.filter(User.subscription_end > datetime.utcnow())
            else:
                query = query.filter(User.subscription_end <= datetime.utcnow())
        return query.all()

async def create_static_profile(name: str, vless_url: str):
    with Session() as session:
        profile = StaticProfile(name=name, vless_url=vless_url)
        session.add(profile)
        session.commit()
        logger.info(f"✅ Static profile created: {name}")
        return profile

async def get_static_profiles():
    with Session() as session:
        return session.query(StaticProfile).all()

async def get_user_stats():
    with Session() as session:
        total = session.query(func.count(User.id)).scalar()
        with_sub = session.query(func.count(User.id)).filter(User.subscription_end > datetime.utcnow()).scalar()
        without_sub = total - with_sub
        return total, with_sub, without_sub

async def get_users_with_profiles():
    """Получает всех пользователей с профилями."""
    with Session() as session:
        return session.query(User).filter(User.profiles_data.isnot(None)).all()

async def fix_all_subscription_dates():
    """Исправляет все некорректные даты подписок в базе данных."""
    with Session() as session:
        users = session.query(User).all()
        fixed_count = 0
        for user in users:
            original_end = user.subscription_end
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            if user.subscription_end != original_end:
                fixed_count += 1
                logger.info(f"✅ Fixed subscription date for user {user.telegram_id}: {original_end} -> {user.subscription_end}")
        session.commit()
        logger.info(f"📊 Fixed {fixed_count} subscription dates out of {len(users)} users")
        return fixed_count

async def delete_user(telegram_id: int) -> bool:
    """Удаляет пользователя из базы данных и его профили из 3x-ui."""
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            # Удаляем все профили из 3x-ui
            profiles_to_delete: list[tuple[str, int]] = []  # (email, inbound_id)

            if user.profiles_data:
                try:
                    profiles = json.loads(user.profiles_data)
                    for inbound_id_str, pdata in profiles.items():
                        email = pdata.get("email")
                        if email:
                            profiles_to_delete.append((email, int(inbound_id_str)))
                except Exception as e:
                    logger.error(f"🛑 Error parsing profiles_data for user {telegram_id}: {e}")

            for email, inbound_id in profiles_to_delete:
                try:
                    from functions import delete_client_by_email
                    import asyncio
                    result = asyncio.get_event_loop().run_until_complete(
                        delete_client_by_email(email, inbound_id)
                    )
                    if result:
                        logger.info(f"✅ Deleted profile from 3x-ui for user {telegram_id} (inbound {inbound_id})")
                    else:
                        logger.warning(f"⚠️ Failed to delete profile from 3x-ui for user {telegram_id} (inbound {inbound_id})")
                except Exception as e:
                    logger.error(f"🛑 Error deleting profile from 3x-ui: {e}")

            session.delete(user)
            session.commit()
            logger.info(f"✅ User {telegram_id} deleted from database")
            return True
        else:
            logger.warning(f"⚠️ User {telegram_id} not found in database")
            return False

def validate_and_fix_subscription_date(subscription_end: datetime) -> datetime:
    """Проверяет и исправляет дату окончания подписки."""
    now = datetime.utcnow()
    if isinstance(subscription_end, str):
        try:
            subscription_end = datetime.fromisoformat(subscription_end)
        except Exception as e:
            logger.error(f"🛑 Ошибка конвертации строки в datetime: {e}, value: {subscription_end}")
            return now + timedelta(days=3)
    if not isinstance(subscription_end, datetime):
        logger.error(f"🛑 subscription_end не является datetime: {type(subscription_end)}, value: {subscription_end}")
        return now + timedelta(days=3)
    if subscription_end < datetime(2020, 1, 1) or subscription_end > now + timedelta(days=3650):
        logger.warning(f"⚠️ Invalid subscription date detected: {subscription_end}, resetting to current time")
        return now + timedelta(days=3)
    return subscription_end
