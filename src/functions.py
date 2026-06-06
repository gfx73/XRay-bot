import aiohttp
import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from config import config

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


# ──────────────────────────────────────────────────────────────
# Основной класс API 3x-ui (v3.2.8+)
# ──────────────────────────────────────────────────────────────

class XUIAPI:
    def __init__(self):
        self.session = None

    async def login(self):
        """Создаёт сессию с Bearer API-токеном (3x-ui v3.0.2+)."""
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

    async def create_client(
        self,
        telegram_id: int,
        expiry_time: int,
        inbound_cfgs: list[dict],
        email_suffix: str = "",
        traffic_limit_gb: int = 0,
    ) -> Optional[dict]:
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

        # Определяем flow из первого Reality-инбаунда
        flow = ""
        for cfg in inbound_cfgs:
            if cfg.get("protocol") == "reality":
                inbound = await self.get_inbound(cfg["id"])
                if inbound:
                    try:
                        settings = json.loads(inbound.get("settings", "{}"))
                        clients = settings.get("clients", [])
                        if clients:
                            flow = clients[0].get("flow", "")
                        if not flow:
                            stream = json.loads(inbound.get("streamSettings", "{}"))
                            if stream.get("realitySettings"):
                                flow = "xtls-rprx-vision"
                    except Exception:
                        flow = "xtls-rprx-vision"
                break

        payload = {
            "client": {
                "id": client_id,
                "email": email,
                "subId": sub_id,
                "flow": flow,
                "expiryTime": expiry_ms,
                "enable": True,
                "limitIp": 0,
                "totalGB": traffic_limit_gb * 1024 ** 3,
                "tgId": 0,
                "reset": 0,
            },
            "inboundIds": inbound_ids,
        }

        url = f"{self._api_base()}/api/clients/add"
        logger.info(f"ℹ️  Creating client {email} in inbounds {inbound_ids}")
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

        # Забираем port и remark из каждого инбаунда для генерации VLESS URL
        inbounds_meta = {}
        for cfg in inbound_cfgs:
            inbound = await self.get_inbound(cfg["id"])
            if inbound:
                inbounds_meta[str(cfg["id"])] = {
                    "port": inbound.get("port"),
                    "remark": inbound.get("remark", ""),
                }

        logger.info(f"✅ Client created: {email} in inbounds {inbound_ids}")
        return {
            "email": email,
            "uuid": client_id,
            "sub_id": sub_id,
            "inbound_ids": inbound_ids,
            "inbounds": inbounds_meta,
        }

    async def create_static_client(self, profile_name: str):
        """Создаёт статический клиент в первом Basic-инбаунде."""
        basic_configs = config.get_inbound_configs("basic")
        if not basic_configs:
            logger.error("🛑 No basic inbounds configured for static client")
            return None

        if not await self.login():
            return None

        inbound_cfg = basic_configs[0]
        inbound_id = inbound_cfg["id"]
        protocol = inbound_cfg.get("protocol", "reality")

        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return None

        client_id = str(uuid.uuid4())
        sub_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static_{profile_name}"))

        # Определяем flow для Reality
        flow = ""
        if protocol == "reality":
            try:
                settings = json.loads(inbound.get("settings", "{}"))
                clients = settings.get("clients", [])
                if clients:
                    flow = clients[0].get("flow", "")
                if not flow:
                    stream = json.loads(inbound.get("streamSettings", "{}"))
                    if stream.get("realitySettings"):
                        flow = "xtls-rprx-vision"
            except Exception:
                flow = "xtls-rprx-vision"

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

        # Строим profile_data совместимый с generate_vless_url (старый формат)
        profile_data = {
            "client_id": client_id,
            "email": profile_name,
            "port": inbound.get("port"),
            "remark": inbound.get("remark", ""),
            "sub_id": sub_id,
            "inbound_id": inbound_id,
        }
        if protocol == "reality":
            profile_data.update({
                "security": "reality",
                "sni": inbound_cfg.get("sni", ""),
                "pbk": inbound_cfg.get("public_key", ""),
                "fp": inbound_cfg.get("fingerprint", ""),
                "sid": inbound_cfg.get("short_id", ""),
                "spx": inbound_cfg.get("spider_x", ""),
            })
        else:
            profile_data.update({
                "security": inbound_cfg.get("security", "tls"),
                "protocol_type": protocol,
                "path": inbound_cfg.get("path", "/"),
                "host": inbound_cfg.get("host", config.XUI_HOST),
                "sni": inbound_cfg.get("sni", config.XUI_HOST),
            })
        return profile_data

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

    async def update_client_expiry(self, email: str, expiry_time: int):
        """Обновляет expiry клиента по email (применяется ко всем инбаундам)."""
        logger.info(f"🔍 [update_client_expiry] email={email}, expiry_time={expiry_time}")
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

        try:
            url = f"{self._api_base()}/api/clients/update/{email}"
            async with self.session.post(url, json={"expiryTime": expiry_ms}) as resp:
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
            settings = json.loads(inbound["settings"])
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
) -> Optional[dict]:
    """Создаёт клиента во всех указанных инбаундах."""
    api = XUIAPI()
    try:
        return await api.create_client(telegram_id, expiry_time, inbound_cfgs, email_suffix, traffic_limit_gb)
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


async def update_client_expiry(email: str, expiry_time: int):
    """Обновляет expiry клиента по email (все инбаунды)."""
    api = XUIAPI()
    try:
        return await api.update_client_expiry(email, expiry_time)
    finally:
        await api.close()


async def get_global_stats():
    """Агрегирует статистику по всем сконфигурированным инбаундам."""
    all_inbound_ids: set[int] = set()
    for tier in ("basic", "premium"):
        for cfg in config.get_inbound_configs(tier):
            all_inbound_ids.add(cfg["id"])
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

def generate_sub_url(sub_id: str) -> str:
    """Генерирует ссылку на подписку 3x-ui."""
    if not config.SUBSCRIPTION_URL_BASE:
        from urllib.parse import urlparse
        parsed = urlparse(config.XUI_API_URL)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        return f"{scheme}://{host}:{config.XUI_SUB_PORT}/sub/{sub_id}"
    return f"{config.SUBSCRIPTION_URL_BASE.rstrip('/')}:{config.XUI_SUB_PORT}/sub/{sub_id}"


def generate_vless_url(profile_data: dict) -> str:
    """Генерирует VLESS URL из старого формата profile_data (статические профили)."""
    remark = profile_data.get('remark', '')
    email = profile_data.get('email', '')
    fragment = f"{remark}-{email}" if remark else email
    security = profile_data.get('security', 'reality')
    client_id = profile_data.get('client_id', '')
    port = profile_data.get('port', 443)

    if security == 'reality':
        pbk = profile_data.get('pbk', '')
        fp = profile_data.get('fp', '')
        sni = profile_data.get('sni', '')
        sid = profile_data.get('sid', '')
        spx = profile_data.get('spx', '')
        return (
            f"vless://{client_id}@{config.XUI_HOST}:{port}"
            f"?type=tcp&security=reality"
            f"&pbk={pbk}&fp={fp}&sni={sni}&sid={sid}&spx={spx}"
            f"#{fragment}"
        )
    else:
        path = profile_data.get('path', '/')
        host = profile_data.get('host', config.XUI_HOST)
        sni = profile_data.get('sni', config.XUI_HOST)
        return (
            f"vless://{client_id}@{config.XUI_HOST}:{port}"
            f"?type=xhttp&security={security}"
            f"&path={path}&host={host}&sni={sni}"
            f"#{fragment}"
        )


def generate_vless_url_v2(inbound_cfg: dict, client_uuid: str, port: int, remark: str) -> str:
    """Генерирует VLESS URL из унифицированного профиля (v3.2.8)."""
    host = config.XUI_HOST
    protocol = inbound_cfg.get("protocol", "reality")

    if protocol == "reality":
        pbk = inbound_cfg.get("public_key", "")
        fp = inbound_cfg.get("fingerprint", "")
        sni = inbound_cfg.get("sni", "")
        sid = inbound_cfg.get("short_id", "")
        spx = inbound_cfg.get("spider_x", "")
        return (
            f"vless://{client_uuid}@{host}:{port}"
            f"?type=tcp&security=reality"
            f"&pbk={pbk}&fp={fp}&sni={sni}&sid={sid}&spx={spx}"
            f"#{remark}"
        )
    else:
        security = inbound_cfg.get("security", "tls")
        path = inbound_cfg.get("path", "/")
        sni = inbound_cfg.get("sni", host)
        h = inbound_cfg.get("host", host) or host
        return (
            f"vless://{client_uuid}@{host}:{port}"
            f"?type=xhttp&security={security}"
            f"&path={path}&host={h}&sni={sni}"
            f"#{remark}"
        )


# ──────────────────────────────────────────────────────────────
# Timestamp / expiry утилиты
# ──────────────────────────────────────────────────────────────

def get_safe_expiry_timestamp(subscription_end) -> int:
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

async def check_and_fix_subscriptions() -> dict:
    """Проверяет и исправляет расхождения между 3x-ui и базой данных."""
    api = XUIAPI()
    try:
        all_inbound_ids: set[int] = set()
        for tier in ("basic", "premium"):
            for cfg in config.get_inbound_configs(tier):
                all_inbound_ids.add(cfg["id"])

        logger.info(f"🔍 [check_and_fix] Checking inbounds: {all_inbound_ids}")

        all_clients_3xui: list[dict] = []
        for inbound_id in all_inbound_ids:
            clients = await api.get_all_clients(inbound_id)
            if clients:
                for c in clients:
                    all_clients_3xui.append({**c, "_inbound_id": inbound_id})

        if not all_clients_3xui:
            return {"error": "Failed to get clients from 3x-ui"}

        from database import get_users_with_profiles
        users_db = await get_users_with_profiles()

        # Маппинг email → (user, первый inbound_id) для всех клиентов (standard + wl)
        users_map: dict[str, tuple] = {}
        for user in users_db:
            if not user.profiles_data:
                continue
            try:
                profiles = json.loads(user.profiles_data)
                if not isinstance(profiles, dict) or "standard" not in profiles:
                    continue
                for slot_profile in profiles.values():
                    if not isinstance(slot_profile, dict):
                        continue
                    email = slot_profile.get("email")
                    if email:
                        first_iid = slot_profile.get("inbound_ids", [None])[0]
                        users_map[email] = (user, first_iid)
            except Exception as e:
                logger.error(f"🛑 Error parsing profiles_data for user {user.telegram_id}: {e}")

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

            if not email or email == "Base":
                continue

            # Для unified-клиентов один email появляется в нескольких инбаундах —
            # достаточно проверить один раз
            if email in seen_emails:
                continue
            seen_emails.add(email)

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

            user, db_inbound_id = users_map[email]
            try:
                if isinstance(user.subscription_end, str):
                    sub_end_db = datetime.fromisoformat(user.subscription_end)
                else:
                    sub_end_db = user.subscription_end

                expiry_time_db = int(sub_end_db.timestamp()) if sub_end_db > datetime.utcnow() else 0
                diff = abs(expiry_time_3xui_seconds - expiry_time_db)

                if diff <= 60:
                    stats["matched"] += 1
                    stats["details"].append({
                        "email": email,
                        "telegram_id": user.telegram_id,
                        "status": "matched",
                        "expiry_3xui": expiry_time_3xui_seconds,
                        "expiry_db": expiry_time_db,
                        "diff": diff,
                        "inbound_id": inbound_id,
                    })
                else:
                    stats["mismatch"] += 1
                    logger.warning(f"⚠️ Mismatch for {email}: 3x-ui={expiry_time_3xui_seconds}, DB={expiry_time_db}")
                    try:
                        result = await force_update_profile_expiry(email, user.subscription_end)
                        status = "fixed" if result else "fix_failed"
                        if result:
                            stats["fixed"] += 1
                        stats["details"].append({
                            "email": email,
                            "telegram_id": user.telegram_id,
                            "status": status,
                            "expiry_3xui": expiry_time_3xui_seconds,
                            "expiry_db": expiry_time_db,
                            "diff": diff,
                            "inbound_id": inbound_id,
                        })
                    except Exception as e:
                        logger.error(f"🛑 Error fixing subscription for {email}: {e}")
                        stats["details"].append({
                            "email": email,
                            "telegram_id": user.telegram_id,
                            "status": "fix_error",
                            "error": str(e),
                            "inbound_id": inbound_id,
                        })
            except Exception as e:
                logger.error(f"🛑 Error processing user {user.telegram_id}: {e}")

        logger.info(f"📊 Subscription check completed: {stats}")
        return stats

    except Exception as e:
        logger.exception(f"🛑 Error in check_and_fix_subscriptions: {e}")
        return {"error": str(e)}
    finally:
        await api.close()
