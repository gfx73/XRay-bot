import aiohttp
import uuid
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Optional
from config import config
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────

def safe_json_loads(value, default=None):
    """Безопасный JSON-парсинг с дефолтным значением."""
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


# ──────────────────────────────────────────────────────────────
# Основной класс API 3x-ui
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

    async def get_inbound(self, inbound_id: int):
        """Получение данных инбаунда."""
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/get/{inbound_id}"
            logger.info(f"ℹ️  Getting inbound data from: {url}")

            async with self.session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Get inbound failed: status={resp.status}, response={text[:100]}...")
                    return None
                try:
                    data = await resp.json()
                    if data.get("success"):
                        return data.get("obj")
                    else:
                        logger.error(f"🛑 Get inbound failed: {data.get('msg')}")
                        return None
                except Exception:
                    text = await resp.text()
                    logger.error(f"🛑 Get inbound response error: {text[:100]}...")
                    return None
        except Exception as e:
            logger.exception(f"🛑 Get inbound error: {e}")
            return None

    async def update_inbound(self, inbound_id: int, data: dict):
        """Обновление инбаунда."""
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/update/{inbound_id}"
            logger.info(f"ℹ️  Updating inbound at: {url}")

            if "settings" in data:
                try:
                    settings = json.loads(data["settings"])
                    clients = settings.get("clients", [])
                    logger.info(f"🔍 [update_inbound] Total clients: {len(clients)}")
                    for i, client in enumerate(clients):
                        email = client.get("email", "unknown")
                        expiry_time = client.get("expiryTime", "not set")
                        logger.info(f"🔍 [update_inbound] Client {i}: {email}, expiryTime: {expiry_time}")
                except Exception:
                    logger.warning("⚠️ Could not parse settings for logging")

            async with self.session.post(url, json=data) as resp:
                logger.info(f"🔍 [update_inbound] Response status: {resp.status}")
                if resp.status != 200:
                    logger.error(f"🛑 Update inbound failed with status: {resp.status}")
                    text = await resp.text()
                    logger.error(f"🛑 Response text: {text[:200]}")
                    return False
                try:
                    response = await resp.json()
                    logger.info(f"🔍 [update_inbound] Response: {response}")
                    return response.get("success", False)
                except Exception:
                    text = await resp.text()
                    return "success" in text.lower()
        except Exception as e:
            logger.exception(f"🛑 Update inbound error: {e}")
            return False

    async def _get_flow_from_inbound(self, inbound: dict) -> str:
        """Получает flow из настроек инбаунда (для Reality)."""
        try:
            settings = json.loads(inbound.get("settings", "{}"))
            stream_settings = json.loads(inbound.get("streamSettings", "{}"))
            reality_settings = stream_settings.get("realitySettings", {})

            if reality_settings:
                clients = settings.get("clients", [])
                if clients and len(clients) > 0:
                    existing_flow = clients[0].get("flow", "")
                    if existing_flow:
                        return existing_flow
                return reality_settings.get("flow", "")

            clients = settings.get("clients", [])
            if clients and len(clients) > 0:
                existing_flow = clients[0].get("flow", "")
                if existing_flow:
                    return existing_flow
        except Exception as e:
            logger.warning(f"⚠️ Could not get flow from inbound: {e}")
        return ""

    # ────────────────────────────────────────────────────────
    # Создание профилей
    # ────────────────────────────────────────────────────────

    async def create_profile(self, telegram_id: int, expiry_time: int, inbound_cfg: dict) -> Optional[dict]:
        """Универсальное создание клиента в указанном инбаунде.

        Args:
            telegram_id: Telegram ID пользователя
            expiry_time: Unix-timestamp истечения (0 = бессрочно)
            inbound_cfg: Конфиг инбаунда из config.get_inbound_configs()
                         {"id": int, "protocol": "reality"|"xhttp", ...}
        Returns:
            profile_data dict или None
        """
        inbound_id = inbound_cfg["id"]
        protocol = inbound_cfg.get("protocol", "reality")
        logger.info(f"🔍 [create_profile] Creating {protocol} profile for user {telegram_id}, inbound={inbound_id}")

        if not await self.login():
            logger.error("🛑 Login failed before creating profile")
            return None

        if expiry_time < 0:
            logger.warning(f"⚠️ Expiry time is in the past ({expiry_time}), setting to 0")
            expiry_time = 0

        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            logger.error(f"🛑 Inbound {inbound_id} not found")
            return None

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])

            client_id = str(uuid.uuid4())
            email = f"user_{telegram_id}_{random.randint(1000, 9999)}"
            sub_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{telegram_id}"))

            expiry_ms = expiry_time * 1000
            if expiry_time != 0 and (expiry_time < 1577836800 or expiry_time > 2000000000):
                logger.error(f"🚨 EMERGENCY: Expiry time is invalid ({expiry_time}), setting to 0!")
                expiry_ms = 0

            if protocol == "reality":
                flow = await self._get_flow_from_inbound(inbound)
                new_client = {
                    "id": client_id,
                    "flow": flow,
                    "email": email,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": expiry_ms,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "reset": 0,
                    "fingerprint": inbound_cfg.get("fingerprint", ""),
                    "publicKey": inbound_cfg.get("public_key", ""),
                    "shortId": inbound_cfg.get("short_id", ""),
                    "spiderX": inbound_cfg.get("spider_x", ""),
                }
            else:
                # xhttp / other transports — НЕТ Reality-полей
                new_client = {
                    "id": client_id,
                    "flow": "",
                    "email": email,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": expiry_ms,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "reset": 0,
                }

            clients.append(new_client)
            settings["clients"] = clients

            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
            }

            if await self.update_inbound(inbound_id, update_data):
                profile_data = {
                    "client_id": client_id,
                    "email": email,
                    "port": inbound["port"],
                    "remark": inbound["remark"],
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
                    security = inbound_cfg.get("security", "tls")
                    profile_data.update({
                        "security": security,
                        "protocol_type": protocol,
                        "path": inbound_cfg.get("path", "/"),
                        "host": inbound_cfg.get("host", config.XUI_HOST),
                        "sni": inbound_cfg.get("sni", config.XUI_HOST),
                    })
                logger.info(f"✅ Profile created: {email} in inbound {inbound_id}")
                return profile_data
            return None
        except Exception as e:
            logger.exception(f"🛑 Create profile error: {e}")
            return None

    async def create_static_client(self, profile_name: str):
        """Создание статического клиента в первом Basic-инбаунде."""
        basic_configs = config.get_inbound_configs("basic")
        if not basic_configs:
            logger.error("🛑 No basic inbounds configured for static client")
            return None

        inbound_cfg = basic_configs[0]
        inbound_id = inbound_cfg["id"]
        protocol = inbound_cfg.get("protocol", "reality")

        if not await self.login():
            logger.error("🛑 Login failed before creating static client")
            return None

        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            logger.error(f"🛑 Inbound {inbound_id} not found")
            return None

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            client_id = str(uuid.uuid4())
            sub_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static_{profile_name}"))

            if protocol == "reality":
                flow = await self._get_flow_from_inbound(inbound)
                new_client = {
                    "id": client_id,
                    "flow": flow,
                    "email": profile_name,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "reset": 0,
                    "fingerprint": inbound_cfg.get("fingerprint", ""),
                    "publicKey": inbound_cfg.get("public_key", ""),
                    "shortId": inbound_cfg.get("short_id", ""),
                    "spiderX": inbound_cfg.get("spider_x", ""),
                }
            else:
                new_client = {
                    "id": client_id,
                    "flow": "",
                    "email": profile_name,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "reset": 0,
                }

            clients.append(new_client)
            settings["clients"] = clients

            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
            }

            if await self.update_inbound(inbound_id, update_data):
                profile_data = {
                    "client_id": client_id,
                    "email": profile_name,
                    "port": inbound["port"],
                    "remark": inbound["remark"],
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
            return None
        except Exception as e:
            logger.exception(f"🛑 Create static client error: {e}")
            return None

    # ────────────────────────────────────────────────────────
    # Управление клиентами
    # ────────────────────────────────────────────────────────

    async def delete_client(self, email: str, inbound_id: int):
        """Удаление клиента по email из указанного инбаунда."""
        if not await self.login():
            return False

        try:
            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                return False

            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            new_clients = [c for c in clients if c["email"] != email]

            if len(new_clients) == len(clients):
                logger.warning(f"⚠️ Client {email} not found in inbound {inbound_id}")
                return False

            settings["clients"] = new_clients
            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
            }
            return await self.update_inbound(inbound_id, update_data)
        except Exception as e:
            logger.exception(f"🛑 Delete client error: {e}")
            return False

    async def update_client_expiry(self, email: str, expiry_time: int, inbound_id: int):
        """Обновление времени истечения подписки клиента.

        Args:
            email: Email клиента
            expiry_time: Новое время истечения в timestamp (0 = бессрочно)
            inbound_id: ID инбаунда
        """
        logger.info(f"🔍 [update_client_expiry] Updating client {email} with expiry_time: {expiry_time}, inbound: {inbound_id}")

        if not await self.login():
            return False

        if expiry_time < 0:
            logger.warning(f"⚠️ Expiry time is in the past ({expiry_time}), setting to 0")
            expiry_time = 0

        try:
            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                return False

            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])

            updated = False
            for client in clients:
                if client["email"] == email:
                    final_expiry_time = expiry_time
                    if expiry_time != 0 and (expiry_time < 1577836800 or expiry_time > 2000000000):
                        logger.error(f"🚨 EMERGENCY: Expiry time is invalid ({expiry_time}), setting to 0!")
                        final_expiry_time = 0
                    client["expiryTime"] = final_expiry_time * 1000
                    updated = True
                    logger.info(f"✅ Updated expiry time for {email}: {final_expiry_time * 1000} ms")
                    break

            if not updated:
                logger.warning(f"⚠️ Client {email} not found for expiry update in inbound {inbound_id}")
                return False

            settings["clients"] = clients
            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
                "allocate": inbound.get("allocate", "")
            }
            return await self.update_inbound(inbound_id, update_data)
        except Exception as e:
            logger.exception(f"🛑 Update client expiry error: {e}")
            return False

    async def get_all_clients(self, inbound_id: int):
        """Получает всех клиентов из указанного инбаунда."""
        if not await self.login():
            logger.error("🛑 Login failed before getting clients")
            return None

        try:
            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                logger.error(f"🛑 Inbound {inbound_id} not found")
                return None
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            logger.info(f"📋 Retrieved {len(clients)} clients from inbound {inbound_id}")
            return clients
        except Exception as e:
            logger.exception(f"🛑 Get all clients error: {e}")
            return None

    # ────────────────────────────────────────────────────────
    # Статистика
    # ────────────────────────────────────────────────────────

    async def get_user_stats(self, email: str):
        """Получение статистики по email."""
        if not await self.login():
            logger.error("🛑 Login failed before getting stats")
            return {"upload": 0, "download": 0}
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/getClientTraffics/{email}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                try:
                    data = await resp.json()
                    if data.get("success"):
                        client_data = data.get("obj")
                        if isinstance(client_data, dict):
                            return {
                                "upload": client_data.get("up", 0),
                                "download": client_data.get("down", 0)
                            }
                except Exception:
                    return {"upload": 0, "download": 0}
        except Exception as e:
            logger.error(f"🛑 Stats error: {e}")
        return {"upload": 0, "download": 0}

    async def get_global_stats(self, inbound_id: int):
        """Получение статистики инбаунда."""
        if not await self.login():
            logger.error("🛑 Login failed before getting stats")
            return {"upload": 0, "download": 0}
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/get/{inbound_id}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                try:
                    data = await resp.json()
                    if data.get("success"):
                        client_data = data.get("obj")
                        if isinstance(client_data, dict):
                            return {
                                "upload": client_data.get("up", 0),
                                "download": client_data.get("down", 0)
                            }
                except Exception:
                    return {"upload": 0, "download": 0}
        except Exception as e:
            logger.error(f"🛑 Stats error: {e}")
        return {"upload": 0, "download": 0}

    async def get_online_users(self):
        if not await self.login():
            logger.error("🛑 Login failed before getting online users")
            return 0
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/onlines"
            async with self.session.post(url) as resp:
                if resp.status != 200:
                    return 0
                try:
                    data = await resp.json()
                    logger.debug(data)
                    online = 0
                    if data.get("success"):
                        users = data.get("obj")
                        if isinstance(users, list):
                            for user in users:
                                if str(user).startswith("user_"):
                                    online += 1
                    return online
                except Exception:
                    return 0
        except Exception as e:
            logger.error(f"🛑 Online users error: {e}")
        return 0

    async def close(self):
        if self.session:
            await self.session.close()


# ──────────────────────────────────────────────────────────────
# Модульные обёртки (используются из handlers.py и app.py)
# ──────────────────────────────────────────────────────────────

async def create_profile(telegram_id: int, expiry_time: int, inbound_cfg: dict) -> Optional[dict]:
    """Создаёт профиль в указанном инбаунде (универсальная функция)."""
    api = XUIAPI()
    try:
        return await api.create_profile(telegram_id, expiry_time, inbound_cfg)
    finally:
        await api.close()


async def create_static_client(profile_name: str):
    api = XUIAPI()
    try:
        return await api.create_static_client(profile_name)
    finally:
        await api.close()


async def delete_client_by_email(email: str, inbound_id: int):
    """Удаляет клиента по email из указанного инбаунда."""
    api = XUIAPI()
    try:
        return await api.delete_client(email, inbound_id)
    finally:
        await api.close()


async def update_client_expiry(email: str, expiry_time: int, inbound_id: int):
    """Обновляет expiry клиента в указанном инбаунде."""
    api = XUIAPI()
    try:
        return await api.update_client_expiry(email, expiry_time, inbound_id)
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
    """Генерирует VLESS URL из profile_data. Поддерживает Reality и xhttp."""
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
        # xhttp / tls / none
        path = profile_data.get('path', '/')
        host = profile_data.get('host', config.XUI_HOST)
        sni = profile_data.get('sni', config.XUI_HOST)
        return (
            f"vless://{client_id}@{config.XUI_HOST}:{port}"
            f"?type=xhttp&security={security}"
            f"&path={path}&host={host}&sni={sni}"
            f"#{fragment}"
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


async def force_update_profile_expiry(email: str, subscription_end, inbound_id: int) -> bool:
    """Принудительно обновляет время истечения существующего профиля."""
    try:
        logger.info(f"🔍 [force_update_profile_expiry] email: {email}, inbound: {inbound_id}")
        expiry_time = get_safe_expiry_timestamp(subscription_end)
        logger.info(f"🔄 Force updating profile {email} with expiry_time: {expiry_time}")
        result = await update_client_expiry(email, expiry_time, inbound_id)
        if result:
            logger.info(f"✅ Successfully force updated profile {email}")
        else:
            logger.error(f"🛑 Failed to force update profile {email}")
        return result
    except Exception as e:
        logger.error(f"🛑 Error force updating profile {email}: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# Проверка и исправление подписок
# ──────────────────────────────────────────────────────────────

async def check_and_fix_subscriptions() -> dict:
    """Проверяет и исправляет расхождения между 3x-ui и базой данных.
    Охватывает все инбаунды из обоих тарифов (basic + premium).
    """
    api = XUIAPI()
    try:
        # Собираем уникальные inbound_id из обоих тарифов
        all_inbound_ids: set[int] = set()
        for tier in ("basic", "premium"):
            for cfg in config.get_inbound_configs(tier):
                all_inbound_ids.add(cfg["id"])

        logger.info(f"🔍 [check_and_fix] Checking inbounds: {all_inbound_ids}")

        # Получаем клиентов из всех инбаундов (с пометкой откуда)
        all_clients_3xui: list[dict] = []
        for inbound_id in all_inbound_ids:
            clients = await api.get_all_clients(inbound_id)
            if clients:
                for c in clients:
                    all_clients_3xui.append({**c, "_inbound_id": inbound_id})

        if not all_clients_3xui:
            return {"error": "Failed to get clients from 3x-ui"}

        # Пользователи из БД
        from database import get_users_with_profiles
        users_db = await get_users_with_profiles()

        # Маппинг email → (user, inbound_id)
        users_map: dict[str, tuple] = {}
        for user in users_db:
            if user.profiles_data:
                try:
                    profiles = json.loads(user.profiles_data)
                    for inbound_id_str, pdata in profiles.items():
                        email = pdata.get("email")
                        if email:
                            users_map[email] = (user, int(inbound_id_str))
                except Exception as e:
                    logger.error(f"🛑 Error parsing profiles_data for user {user.telegram_id}: {e}")

        stats = {
            "total_3xui": len(all_clients_3xui),
            "total_db": len(users_db),
            "matched": 0,
            "mismatch": 0,
            "fixed": 0,
            "not_in_db": 0,
            "details": []
        }

        for client in all_clients_3xui:
            email = client.get("email")
            expiry_time_3xui = client.get("expiryTime", 0)
            inbound_id = client.get("_inbound_id", 0)

            if not email or email == "Base":
                continue

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
                    logger.warning(f"⚠️ Mismatch for {email} (inbound {inbound_id}): 3x-ui={expiry_time_3xui_seconds}, DB={expiry_time_db}, diff={diff}")
                    try:
                        result = await force_update_profile_expiry(email, user.subscription_end, inbound_id)
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
