import json
import logging
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

import aiohttp

from config import config
from models import InboundMeta, ProfileSlot, SlotName, UserProfiles

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────

def safe_json_loads(value, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _as_dict(v) -> dict:
    """Return v as a dict, parsing JSON string if needed."""
    if isinstance(v, dict):
        return v
    if not v:
        return {}
    return json.loads(v)


# ──────────────────────────────────────────────────────────────
# Основной класс API 3x-ui (v3.2.8+)
# ──────────────────────────────────────────────────────────────

class XUIAPI:
    def __init__(self):
        self.session = None

    async def login(self):
        """Создаёт сессию с Bearer API-токеном (3x-ui v3.0.2+)."""
        if self.session is not None and not self.session.closed:
            return True
        if not config.XUI_API_TOKEN:
            logger.error("🛑 XUI_API_TOKEN is not set")
            return False
        connector = aiohttp.TCPConnector(ssl=config.XUI_VERIFY_SSL)
        self.session = aiohttp.ClientSession(
            connector=connector,
            headers={"Authorization": f"Bearer {config.XUI_API_TOKEN}"},
        )
        logger.info("✅ Session created with Bearer token")
        return True

    def _api_base(self) -> str:
        base_url = config.XUI_API_URL.rstrip('/')
        base_path = config.XUI_BASE_PATH.strip('/')
        if base_path:
            base_url = f"{base_url}/{base_path}"
        return base_url

    async def get_inbound(self, inbound_id: int):
        """Получение данных инбаунда."""
        try:
            url = f"{self._api_base()}/api/inbounds/get/{inbound_id}"
            logger.info(f"ℹ️  Getting inbound data from: {url}")
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Get inbound failed: status={resp.status}, response={text[:100]}")
                    return None
                data = await resp.json()
                if data.get("success"):
                    return data.get("obj")
                logger.error(f"🛑 Get inbound failed: {data.get('msg')}")
                return None
        except Exception as e:
            logger.exception(f"🛑 Get inbound error: {e}")
            return None

    # ────────────────────────────────────────────────────────
    # Создание клиентов (v3.2.8 unified API)
    # ────────────────────────────────────────────────────────

    async def _prepare_inbound_data(self, inbound_cfgs: list[dict]) -> tuple[str, dict]:
        """Fetch each inbound once; return (reality_flow, inbounds_meta)."""
        flow = ""
        inbounds_meta = {}
        for cfg in inbound_cfgs:
            inbound = await self.get_inbound(cfg["id"])
            if not inbound:
                logger.warning(f"⚠️  _prepare_inbound_data: get_inbound({cfg['id']}) returned None")
                continue
            inbounds_meta[str(cfg["id"])] = {
                "port": inbound.get("port"),
                "remark": inbound.get("remark", ""),
            }
            if not flow:
                stream = _as_dict(inbound.get("streamSettings"))
                security = stream.get("security", "")
                logger.info(f"🔍 Inbound {cfg['id']}: security={security!r}")
                if security == "reality":
                    settings = _as_dict(inbound.get("settings"))
                    clients = settings.get("clients", [])
                    detected = clients[0].get("flow", "") if clients else ""
                    flow = detected or "xtls-rprx-vision"
                    logger.info(f"✅ Reality flow detected for inbound {cfg['id']}: {flow!r}")
        if not flow:
            logger.info("ℹ️  No Reality inbound found — flow set to empty string")
        return flow, inbounds_meta

    async def create_client(
        self,
        telegram_id: int,
        expiry_time: int,
        inbound_cfgs: list[dict],
        email_suffix: str = "",
        traffic_limit_gb: int = 0,
        ip_limit: int = 0,
    ) -> ProfileSlot | None:
        """Создаёт клиента во всех указанных инбаундах одним запросом.

        Args:
            email_suffix: суффикс к email (например "_wl" для whitelist-клиента)
            traffic_limit_gb: лимит трафика в ГБ, 0 = безлимит

        Returns:
            {"email", "uuid", "sub_id", "inbound_ids", "inbounds": {id_str: {port, remark}}}
        """
        if not await self.login():
            logger.error("🛑 Login failed before creating client")
            return None

        client_id = str(uuid.uuid4())
        email = f"user_{telegram_id}{email_suffix}"
        sub_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
        inbound_ids = [cfg["id"] for cfg in inbound_cfgs]

        expiry_ms = expiry_time * 1000
        if expiry_time != 0 and (expiry_time < 1577836800 or expiry_time > 2000000000):
            logger.error(f"🚨 Invalid expiry time ({expiry_time}), setting to 0")
            expiry_ms = 0

        flow, inbounds_meta = await self._prepare_inbound_data(inbound_cfgs)

        payload = {
            "client": {
                "id": client_id,
                "email": email,
                "subId": sub_id,
                "flow": flow,
                "expiryTime": expiry_ms,
                "enable": True,
                "limitIp": ip_limit,
                "totalGB": traffic_limit_gb * 1024 ** 3,
                "tgId": 0,
                "reset": 0,
            },
            "inboundIds": inbound_ids,
        }

        url = f"{self._api_base()}/api/clients/add"
        logger.info(
            f"ℹ️  Creating client {email} | inbounds={inbound_ids} | "
            f"flow={flow!r} | limitIp={ip_limit} | totalGB_bytes={traffic_limit_gb * 1024 ** 3} | "
            f"expiryMs={expiry_ms}"
        )
        logger.info(f"📤 Full payload: {json.dumps(payload)}")
        try:
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Create client failed: status={resp.status}, body={text[:200]}")
                    return None
                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"🛑 Create client failed: {data.get('msg')}")
                    return None
        except Exception as e:
            logger.exception(f"🛑 Create client error: {e}")
            return None

        logger.info(f"✅ Client created: {email} in inbounds {inbound_ids}")
        return ProfileSlot(
            email=email,
            uuid=client_id,
            sub_id=sub_id,
            inbound_ids=inbound_ids,
            inbounds={k: InboundMeta(**v) for k, v in inbounds_meta.items()},
        )

    async def create_static_client(self, profile_name: str):  # noqa: PLR0911
        """Создаёт статический клиент в первом Basic-инбаунде."""
        basic_configs = config.get_standard_inbounds()
        if not basic_configs:
            logger.error("🛑 No basic inbounds configured for static client")
            return None

        if not await self.login():
            return None

        inbound_cfg = basic_configs[0]
        inbound_id = inbound_cfg["id"]

        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return None

        client_id = str(uuid.uuid4())
        sub_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static_{profile_name}"))

        flow = ""
        stream = _as_dict(inbound.get("streamSettings"))
        if stream.get("security") == "reality":
            settings = _as_dict(inbound.get("settings"))
            clients = settings.get("clients", [])
            flow = clients[0].get("flow", "") if clients else ""
            flow = flow or "xtls-rprx-vision"

        payload = {
            "client": {
                "id": client_id,
                "email": profile_name,
                "subId": sub_id,
                "flow": flow,
                "expiryTime": 0,
                "enable": True,
                "limitIp": 0,
                "totalGB": 0,
                "tgId": 0,
                "reset": 0,
            },
            "inboundIds": [inbound_id],
        }

        url = f"{self._api_base()}/api/clients/add"
        try:
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"🛑 Create static client failed: status={resp.status}")
                    return None
                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"🛑 Create static client failed: {data.get('msg')}")
                    return None
        except Exception as e:
            logger.exception(f"🛑 Create static client error: {e}")
            return None

        sub_url = generate_sub_url(sub_id)
        logger.info(f"✅ Static client created: {profile_name}, sub_url={sub_url}")
        return {"sub_id": sub_id, "sub_url": sub_url}

    # ────────────────────────────────────────────────────────
    # Управление клиентами (v3.2.8 unified API)
    # ────────────────────────────────────────────────────────

    async def delete_client(self, email: str):
        """Удаляет клиента по email из всех инбаундов."""
        if not await self.login():
            return False
        try:
            url = f"{self._api_base()}/api/clients/del/{email}"
            async with self.session.post(url) as resp:
                if resp.status != 200:
                    logger.error(f"🛑 Delete client failed: status={resp.status}")
                    return False
                data = await resp.json()
                success = data.get("success", False)
                if success:
                    logger.info(f"✅ Deleted client: {email}")
                else:
                    logger.warning(f"⚠️ Delete client failed for {email}: {data.get('msg')}")
                return success
        except Exception as e:
            logger.exception(f"🛑 Delete client error: {e}")
            return False

    async def _get_client(self, email: str):
        try:
            get_url = f"{self._api_base()}/api/clients/get/{email}"
            async with self.session.get(get_url) as resp:
                if resp.status != 200:
                    logger.error(f"🛑 Get client failed: status={resp.status}")
                    return None
                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"🛑 Get client failed for {email}: {data.get('msg')}")
                    return None
                return data.get("obj").get("client")
        except Exception as e:
            logger.exception(f"🛑 Get client error: {e}")
            return None

    async def update_client_expiry(self, email: str, expiry_time: int, traffic_limit_gb: int | None = None):
        """Обновляет expiry клиента по email (применяется ко всем инбаундам).

        traffic_limit_gb: если задан — также обновляет лимит трафика (0 = безлимит).
        """
        logger.info(f"🔍 [update_client_expiry] email={email}, expiry_time={expiry_time}, traffic_limit_gb={traffic_limit_gb}")
        if not await self.login():
            return False

        if expiry_time < 0:
            logger.warning(f"⚠️ Expiry time is negative ({expiry_time}), setting to 0")
            expiry_time = 0

        final_expiry = expiry_time
        if expiry_time != 0 and (expiry_time < 1577836800 or expiry_time > 2000000000):
            logger.error(f"🚨 Invalid expiry time ({expiry_time}), setting to 0")
            final_expiry = 0

        expiry_ms = final_expiry * 1000

        current_client = await self._get_client(email)
        if not current_client:
            logger.error(f"🛑 update_client_expiry: client {email!r} not found")
            return False

        new_total_gb = (traffic_limit_gb * 1024 ** 3) if traffic_limit_gb is not None else current_client["totalGB"]
        if current_client.get("expiryTime") == expiry_ms and current_client["totalGB"] == new_total_gb:
            logger.info(f"⏭️ Skipping update for {email}: expiry and traffic already up to date")
            return True

        logger.info(current_client)
        payload = {
            "id": current_client.get("uuid", ""),
            "flow": current_client["flow"],
            "limitIp": current_client["limitIp"],
            "totalGB": new_total_gb,
            "email": email,
            "expiryTime": expiry_ms,
            "enable": True,
        }

        try:
            url = f"{self._api_base()}/api/clients/update/{email}"
            async with self.session.post(url, json=payload) as resp:
                logger.info(f"update expiry payload: {payload}")
                if resp.status != 200:
                    logger.error(f"🛑 Update client expiry failed: status={resp.status}")
                    return False
                data = await resp.json()
                success = data.get("success", False)
                if success:
                    logger.info(f"✅ Updated expiry for {email}: {expiry_ms} ms")
                else:
                    logger.warning(f"⚠️ Update expiry failed for {email}: {data.get('msg')}")
                return success
        except Exception as e:
            logger.exception(f"🛑 Update client expiry error: {e}")
            return False

    # ────────────────────────────────────────────────────────
    # Статистика
    # ────────────────────────────────────────────────────────

    async def get_user_stats(self, email: str):
        """Получение статистики по email клиента."""
        if not await self.login():
            logger.error("🛑 Login failed before getting stats")
            return {"upload": 0, "download": 0}
        try:
            url = f"{self._api_base()}/api/clients/traffic/{email}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                data = await resp.json()
                if data.get("success"):
                    obj = data.get("obj")
                    if isinstance(obj, dict):
                        return {
                            "upload": obj.get("up", 0),
                            "download": obj.get("down", 0),
                        }
        except Exception as e:
            logger.error(f"🛑 Stats error: {e}")
        return {"upload": 0, "download": 0}

    async def get_global_stats(self, inbound_id: int):
        """Получение статистики инбаунда."""
        if not await self.login():
            return {"upload": 0, "download": 0}
        try:
            url = f"{self._api_base()}/api/inbounds/get/{inbound_id}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                data = await resp.json()
                if data.get("success"):
                    obj = data.get("obj")
                    if isinstance(obj, dict):
                        return {
                            "upload": obj.get("up", 0),
                            "download": obj.get("down", 0),
                        }
        except Exception as e:
            logger.error(f"🛑 Stats error: {e}")
        return {"upload": 0, "download": 0}

    async def get_online_users(self):
        if not await self.login():
            logger.error("🛑 Login failed before getting online users")
            return 0
        try:
            url = f"{self._api_base()}/api/clients/onlines"
            async with self.session.post(url) as resp:
                if resp.status != 200:
                    return 0
                data = await resp.json()
                online = 0
                if data.get("success"):
                    users = data.get("obj")
                    if isinstance(users, list):
                        for user in users:
                            if str(user).startswith("user_"):
                                online += 1
                return online
        except Exception as e:
            logger.error(f"🛑 Online users error: {e}")
        return 0

    async def get_all_clients(self, inbound_id: int):
        """Получает всех клиентов из указанного инбаунда."""
        if not await self.login():
            logger.error("🛑 Login failed before getting clients")
            return None
        try:
            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                return None
            settings = inbound["settings"] if isinstance(inbound["settings"], dict) else json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            logger.info(f"📋 Retrieved {len(clients)} clients from inbound {inbound_id}")
            return clients
        except Exception as e:
            logger.exception(f"🛑 Get all clients error: {e}")
            return None

    async def close(self):
        if self.session:
            await self.session.close()


# ──────────────────────────────────────────────────────────────
# Модульные обёртки
# ──────────────────────────────────────────────────────────────

async def create_client(
    telegram_id: int,
    expiry_time: int,
    inbound_cfgs: list[dict],
    email_suffix: str = "",
    traffic_limit_gb: int = 0,
    ip_limit: int = 0,
) -> ProfileSlot | None:
    """Создаёт клиента во всех указанных инбаундах."""
    api = XUIAPI()
    try:
        return await api.create_client(telegram_id, expiry_time, inbound_cfgs, email_suffix, traffic_limit_gb, ip_limit)
    finally:
        await api.close()


async def create_static_client(profile_name: str):
    api = XUIAPI()
    try:
        return await api.create_static_client(profile_name)
    finally:
        await api.close()


async def delete_client_by_email(email: str):
    """Удаляет клиента по email из всех инбаундов."""
    api = XUIAPI()
    try:
        return await api.delete_client(email)
    finally:
        await api.close()


async def update_client_expiry(email: str, expiry_time: int, traffic_limit_gb: int | None = None):
    """Обновляет expiry клиента по email (все инбаунды).

    traffic_limit_gb: если задан — также обновляет лимит трафика.
    """
    api = XUIAPI()
    try:
        return await api.update_client_expiry(email, expiry_time, traffic_limit_gb=traffic_limit_gb)
    finally:
        await api.close()


async def get_global_stats():
    """Агрегирует статистику по всем сконфигурированным инбаундам."""
    all_inbound_ids: set[int] = {
        cfg["id"]
        for cfg in [*config.get_standard_inbounds(), *config.get_wl_inbounds()]
    }
    api = XUIAPI()
    try:
        total = {"upload": 0, "download": 0}
        for inbound_id in all_inbound_ids:
            stats = await api.get_global_stats(inbound_id)
            total["upload"] += stats.get("upload", 0)
            total["download"] += stats.get("download", 0)
        return total
    finally:
        await api.close()


async def get_online_users():
    api = XUIAPI()
    try:
        return await api.get_online_users()
    finally:
        await api.close()


async def get_user_stats(email: str):
    api = XUIAPI()
    try:
        return await api.get_user_stats(email)
    finally:
        await api.close()


# ──────────────────────────────────────────────────────────────
# URL-генерация
# ──────────────────────────────────────────────────────────────

async def _sync_standard_slot(telegram_id: int, expiry: int, existing: UserProfiles) -> ProfileSlot | None:
    """Update expiry for existing standard client or create a new one."""
    if existing.standard is not None:
        await update_client_expiry(existing.standard.email, expiry)
        return existing.standard
    return await create_client(
        telegram_id, expiry, config.get_standard_inbounds(),
        traffic_limit_gb=config.STANDARD_TRAFFIC_LIMIT_GB,
        ip_limit=config.STANDARD_IP_LIMIT,
    )


async def _sync_wl_slot(telegram_id: int, expiry: int, existing: UserProfiles, is_first_purchase: bool = False) -> ProfileSlot | None:
    """Update expiry for existing wl client or create a new one.

    is_first_purchase: если True — также обновляет лимит трафика до полного (WL_TRAFFIC_LIMIT_GB).
    """
    if existing.wl is not None:
        traffic_update = config.WL_TRAFFIC_LIMIT_GB if is_first_purchase else None
        await update_client_expiry(existing.wl.email, expiry, traffic_limit_gb=traffic_update)
        return existing.wl
    return await create_client(
        telegram_id, expiry, config.get_wl_inbounds(),
        email_suffix=f"_{SlotName.WL.value}",
        traffic_limit_gb=config.WL_TRAFFIC_LIMIT_GB,
        ip_limit=config.WL_IP_LIMIT,
    )


async def sync_profiles(
    telegram_id: int,
    expiry: int,
    existing: UserProfiles,
    is_first_purchase: bool = False,
) -> UserProfiles:
    """Sync both VPN profile slots after a subscription payment.

    is_first_purchase: если True — обновляет лимит трафика WL-профиля до полного.
    """
    result = UserProfiles()

    std_slot = await _sync_standard_slot(telegram_id, expiry, existing)
    if std_slot:
        result.standard = std_slot

    if config.has_wl_inbounds():
        wl_slot = await _sync_wl_slot(telegram_id, expiry, existing, is_first_purchase=is_first_purchase)
        if wl_slot:
            result.wl = wl_slot

    return result


def generate_sub_url(sub_id: str) -> str:
    """Генерирует ссылку на подписку 3x-ui."""
    sub_path = config.SUB_BASE_PATH.strip("/")
    if not config.SUBSCRIPTION_URL_BASE:
        parsed = urlparse(config.XUI_API_URL)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        return f"{scheme}://{host}:{config.XUI_SUB_PORT}/{sub_path}/{sub_id}"
    return f"{config.SUBSCRIPTION_URL_BASE.rstrip('/')}:{config.XUI_SUB_PORT}/{sub_path}/{sub_id}"



# ──────────────────────────────────────────────────────────────
# Timestamp / expiry утилиты
# ──────────────────────────────────────────────────────────────

def get_safe_expiry_timestamp(subscription_end) -> int:  # noqa: PLR0911
    """Безопасно получает timestamp из даты окончания подписки."""
    logger.info(f"🔍 [get_safe_expiry_timestamp] Input: {subscription_end}, type: {type(subscription_end)}")

    if subscription_end is None:
        return 0

    if isinstance(subscription_end, str):
        try:
            subscription_end = datetime.fromisoformat(subscription_end)
        except Exception as e:
            logger.error(f"🛑 [get_safe_expiry_timestamp] Conversion error: {e}")
            return 0

    if not isinstance(subscription_end, datetime):
        logger.error(f"🛑 [get_safe_expiry_timestamp] Not a datetime: {type(subscription_end)}")
        return 0

    now = datetime.utcnow()

    if subscription_end < datetime(2020, 1, 1):
        return 0
    if subscription_end > now + timedelta(days=3650):
        return 0
    if subscription_end <= now:
        return 0

    try:
        timestamp = int(subscription_end.timestamp())
        if timestamp < 0 or timestamp < 1577836800:
            return 0
        logger.info(f"✅ [get_safe_expiry_timestamp] Final timestamp: {timestamp}")
        return timestamp
    except Exception as e:
        logger.error(f"🛑 Error converting date to timestamp: {e}")
        return 0


async def force_update_profile_expiry(email: str, subscription_end) -> bool:
    """Принудительно обновляет время истечения существующего клиента."""
    try:
        logger.info(f"🔍 [force_update_profile_expiry] email: {email}")
        expiry_time = get_safe_expiry_timestamp(subscription_end)
        logger.info(f"🔄 Force updating client {email} with expiry_time: {expiry_time}")
        result = await update_client_expiry(email, expiry_time)
        if result:
            logger.info(f"✅ Successfully force updated client {email}")
        else:
            logger.error(f"🛑 Failed to force update client {email}")
        return result
    except Exception as e:
        logger.error(f"🛑 Error force updating client {email}: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# Проверка и исправление подписок
# ──────────────────────────────────────────────────────────────

async def _collect_clients_from_inbounds(api: "XUIAPI", inbound_ids: set[int]) -> list[dict]:
    """Fetch all clients from all given inbound IDs."""
    all_clients: list[dict] = []
    for inbound_id in inbound_ids:
        clients = await api.get_all_clients(inbound_id)
        if clients:
            all_clients.extend({**c, "_inbound_id": inbound_id} for c in clients)
    return all_clients


def _build_email_user_map(users_db: list) -> dict[str, tuple]:
    """Build email → (user, inbound_id) mapping from DB users with profiles."""
    users_map: dict[str, tuple] = {}
    for user in users_db:
        for slot in user.profiles.slots().values():
            first_iid = slot.inbound_ids[0] if slot.inbound_ids else None
            users_map[slot.email] = (user, first_iid)
    return users_map


async def check_and_fix_subscriptions() -> dict:  # noqa: PLR0912, PLR0915
    """Проверяет и исправляет расхождения между 3x-ui и базой данных."""
    api = XUIAPI()
    try:
        all_inbound_ids: set[int] = {
            cfg["id"]
            for cfg in [*config.get_standard_inbounds(), *config.get_wl_inbounds()]
        }

        logger.info(f"🔍 [check_and_fix] Checking inbounds: {all_inbound_ids}")

        all_clients_3xui = await _collect_clients_from_inbounds(api, all_inbound_ids)
        if not all_clients_3xui:
            return {"error": "Failed to get clients from 3x-ui"}

        from database import get_users_with_profiles  # noqa: PLC0415
        users_db = await get_users_with_profiles()
        users_map = _build_email_user_map(users_db)

        stats = {
            "total_3xui": len(all_clients_3xui),
            "total_db": len(users_db),
            "matched": 0,
            "mismatch": 0,
            "fixed": 0,
            "not_in_db": 0,
            "details": [],
        }

        seen_emails: set[str] = set()
        for client in all_clients_3xui:
            email = client.get("email")
            expiry_time_3xui = client.get("expiryTime", 0)
            inbound_id = client.get("_inbound_id", 0)

            if not email or email == "Base" or email in seen_emails:
                continue
            seen_emails.add(email)

            # Для unified-клиентов один email появляется в нескольких инбаундах —
            # достаточно проверить один раз
            expiry_time_3xui_seconds = expiry_time_3xui // 1000 if expiry_time_3xui > 0 else 0

            if email not in users_map:
                stats["not_in_db"] += 1
                stats["details"].append({
                    "email": email,
                    "status": "not_in_db",
                    "expiry_3xui": expiry_time_3xui_seconds,
                    "expiry_db": None,
                    "inbound_id": inbound_id,
                })
                continue

            user, _ = users_map[email]
            try:
                sub_end_raw = user.subscription_end
                if isinstance(sub_end_raw, str):
                    sub_end_db = datetime.fromisoformat(sub_end_raw)
                else:
                    sub_end_db = sub_end_raw

                expiry_time_db = int(sub_end_db.timestamp()) if sub_end_db and sub_end_db > datetime.utcnow() else 0
                diff = abs(expiry_time_3xui_seconds - expiry_time_db)
                detail_base = {
                    "email": email,
                    "telegram_id": user.telegram_id,
                    "expiry_3xui": expiry_time_3xui_seconds,
                    "expiry_db": expiry_time_db,
                    "diff": diff,
                    "inbound_id": inbound_id,
                }

                if diff <= 60:
                    stats["matched"] += 1
                    stats["details"].append({**detail_base, "status": "matched"})
                else:
                    stats["mismatch"] += 1
                    logger.warning(f"⚠️ Mismatch for {email}: 3x-ui={expiry_time_3xui_seconds}, DB={expiry_time_db}")
                    try:
                        expiry_ts = get_safe_expiry_timestamp(sub_end_raw)
                        result = await api.update_client_expiry(email, expiry_ts)
                        status = "fixed" if result else "fix_failed"
                        if result:
                            stats["fixed"] += 1
                        stats["details"].append({**detail_base, "status": status})
                    except Exception as e:
                        logger.error(f"🛑 Error fixing subscription for {email}: {e}")
                        stats["details"].append({**detail_base, "status": "fix_error", "error": str(e)})
            except Exception as e:
                logger.error(f"🛑 Error processing user {user.telegram_id}: {e}")

        logger.info(f"📊 Subscription check completed: {stats}")
        return stats

    except Exception as e:
        logger.exception(f"🛑 Error in check_and_fix_subscriptions: {e}")
        return {"error": str(e)}
    finally:
        await api.close()
