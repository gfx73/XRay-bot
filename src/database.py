import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
    func,
    or_,
)
from sqlalchemy import (
    Enum as SaEnum,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.types import TypeDecorator

from config import config
from functions import delete_client_by_email
from models import SubscriptionTier, UserProfiles

logger = logging.getLogger(__name__)


class PydanticJSON(TypeDecorator):
    """SQLAlchemy column type that transparently stores a Pydantic model as JSON."""
    impl = JSON
    cache_ok = True

    def __init__(self, model_class):
        self.model_class = model_class
        super().__init__()

    def process_bind_param(self, value, dialect):
        if value is None or not value:
            return None
        return value.model_dump(exclude_none=True)

    def process_result_value(self, value, dialect):
        if value is None:
            return self.model_class()
        return self.model_class.model_validate(value)


Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    full_name = Column(String)
    username = Column(String)
    registration_date = Column(DateTime, default=datetime.utcnow)
    subscription_end = Column(DateTime)
    premium_end = Column(DateTime, nullable=True)          # отдельный срок для premium/wl
    is_admin = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)
    premium_notified = Column(Boolean, default=False)
    subscription_tier = Column(SaEnum(SubscriptionTier), default=SubscriptionTier.STANDARD)
    profiles = Column(PydanticJSON(UserProfiles), nullable=True)
    referral_code = Column(String, unique=True, nullable=True)
    referred_by = Column(Integer, nullable=True)

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

async def get_user_by_referral_code(code: str):
    with Session() as session:
        return session.query(User).filter_by(referral_code=code).first()


async def get_referral_count(telegram_id: int) -> int:
    with Session() as session:
        return session.query(func.count(User.id)).filter_by(referred_by=telegram_id).scalar() or 0


async def create_user(
    telegram_id: int,
    full_name: str,
    username: str | None = None,
    is_admin: bool = False,
    referred_by: int | None = None,
):
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
            subscription_tier=SubscriptionTier(config.TRIAL_TIER),
            referral_code=secrets.token_urlsafe(8),
            referred_by=referred_by,
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
            user.profiles = UserProfiles()
            user.notified = False
            user.premium_notified = False
            session.commit()
            logger.info(f"✅ User profile deleted: {telegram_id}")

async def update_subscription(telegram_id: int, months: int = 0, tier: str | None = None, hours: int = 0):
    """Обновляет подписку с учётом текущего состояния.

    tier="basic"   → продлевает subscription_end, premium_end не трогает.
    tier="premium" → продлевает premium_end, subscription_end не трогает.
    hours имеет приоритет над months; если оба 0 — ничего не добавляется.
    """
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            now = datetime.utcnow()
            duration = timedelta(hours=hours) if hours else timedelta(days=months * 30)
            if tier == SubscriptionTier.PREMIUM:
                # subscription_end считается от текущего subscription_end (если активен)
                user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
                if user.subscription_end > now:
                    user.subscription_end += duration
                else:
                    user.subscription_end = now + duration
                user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
                # premium_end считается независимо — от текущего premium_end (если активен), иначе от now
                current_prem = validate_and_fix_subscription_date(user.premium_end) if user.premium_end else now
                if current_prem > now:
                    user.premium_end = current_prem + duration
                else:
                    user.premium_end = now + duration
                user.premium_end = validate_and_fix_subscription_date(user.premium_end)
                user.notified = False
                user.premium_notified = False
            else:
                # Продлеваем только standard; premium_end не трогаем
                user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
                if user.subscription_end > now:
                    user.subscription_end += duration
                else:
                    user.subscription_end = now + duration
                user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
                user.notified = False
            # Derive tier from currently active subscriptions
            has_active_premium = bool(user.premium_end and user.premium_end > now)
            user.subscription_tier = SubscriptionTier.PREMIUM if has_active_premium else SubscriptionTier.STANDARD
            session.commit()
            duration_str = f"{hours}h" if hours else f"{months}mo"
            logger.info(f"✅ Subscription updated for {telegram_id}: +{duration_str}, tier={tier}, "
                        f"subscription_end={user.subscription_end}, premium_end={user.premium_end}")
            return True
        return False

async def get_all_users(with_subscription: bool | None = None):
    with Session() as session:
        query = session.query(User)
        if with_subscription is not None:
            now = datetime.utcnow()
            if with_subscription:
                query = query.filter(
                    or_(User.subscription_end > now, User.premium_end > now)
                )
            else:
                query = query.filter(
                    User.subscription_end <= now,
                    or_(User.premium_end.is_(None), User.premium_end <= now),
                )
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
        now = datetime.utcnow()
        total = session.query(func.count(User.id)).scalar()
        with_sub = session.query(func.count(User.id)).filter(
            or_(User.subscription_end > now, User.premium_end > now)
        ).scalar()
        without_sub = total - with_sub
        return total, with_sub, without_sub

async def get_users_with_profiles():
    """Получает всех пользователей с профилями."""
    with Session() as session:
        return session.query(User).filter(User.profiles.isnot(None)).all()

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
    """Удаляет пользователя из БД и его клиента из 3x-ui."""
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            logger.warning(f"⚠️ User {telegram_id} not found in database")
            return False

        emails_to_delete: set = set()
        for slot in user.profiles.slots().values():
            emails_to_delete.add(slot.email)

        for email in emails_to_delete:
            try:
                result = await delete_client_by_email(email)
                if result:
                    logger.info(f"✅ Deleted 3x-ui client {email} for user {telegram_id}")
                else:
                    logger.warning(f"⚠️ Failed to delete 3x-ui client {email}")
            except Exception as e:
                logger.error(f"🛑 Error deleting 3x-ui client {email}: {e}")

        session.delete(user)
        session.commit()
        logger.info(f"✅ User {telegram_id} deleted from database")
        return True

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
