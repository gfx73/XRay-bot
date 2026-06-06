import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict

load_dotenv()

class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: List[int] = Field(default_factory=list)
    XUI_API_URL: str = os.getenv("XUI_API_URL", "http://localhost:54321")
    XUI_BASE_PATH: str = os.getenv("XUI_BASE_PATH", "/panel")
    XUI_SUB_PORT: str = os.getenv("XUI_SUB_PORT", "54321")
    XUI_USERNAME: str = os.getenv("XUI_USERNAME", "admin")
    XUI_PASSWORD: str = os.getenv("XUI_PASSWORD", "admin")
    XUI_HOST: str = os.getenv("XUI_HOST", "your-server.com")
    XUI_SERVER_NAME: str = os.getenv("XUI_SERVER_NAME", "domain.com")
    XUI_VERIFY_SSL: bool = Field(default=os.getenv("XUI_VERIFY_SSL", "True").lower() == "true")
    PAYMENT_TOKEN: str = os.getenv("PAYMENT_TOKEN", "")

    TEMP_WEB_SERVER_PORT: int = Field(default=os.getenv("TEMP_WEB_SERVER_PORT", 8080))
    TEMP_SSL_CERT_PATH: str = os.getenv("TEMP_SSL_CERT_PATH", "")
    TEMP_SSL_KEY_PATH: str = os.getenv("TEMP_SSL_KEY_PATH", "")

    # ────────────────────────────────────────────────
    # Новая система тарифов
    # Формат: "id:protocol,id:protocol" — например "1:reality,3:xhttp"
    # Параметры каждого инбаунда задаются через INBOUND_{ID}_*
    # ────────────────────────────────────────────────
    BASIC_INBOUNDS: str = os.getenv("BASIC_INBOUNDS", "")
    PREMIUM_INBOUNDS: str = os.getenv("PREMIUM_INBOUNDS", "")

    # Коэффициент цены Premium = цена Basic * PREMIUM_PRICE_MULTIPLIER
    PREMIUM_PRICE_MULTIPLIER: float = Field(
        default=float(os.getenv("PREMIUM_PRICE_MULTIPLIER", "1.5"))
    )

    # Временные тест-инбаунды: "id:protocol,id:protocol"
    TEMP_INBOUND_CONFIGS: str = os.getenv("TEMP_INBOUND_CONFIGS", "")

    # Настройки цен и скидок
    PRICES: Dict[int, Dict[str, int]] = {
        1: {"base_price": 100, "discount_percent": 0},
        3: {"base_price": 300, "discount_percent": 10},
        6: {"base_price": 600, "discount_percent": 20},
        12: {"base_price": 1200, "discount_percent": 30}
    }
    SUBSCRIPTION_URL_BASE: str = os.getenv("SUBSCRIPTION_URL_BASE", "")

    @field_validator('ADMINS', mode='before')
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []

    @field_validator('TEMP_WEB_SERVER_PORT', mode='before')
    def parse_temp_web_server_port(cls, value):
        if isinstance(value, str):
            return int(value)
        return value or 8080

    # ────────────────────────────────────────────────
    # Tribute (опционально)
    # ────────────────────────────────────────────────
    TRIBUTE_API_KEY: str = os.getenv("TRIBUTE_API_KEY", "")
    TRIBUTE_WEBHOOK_PORT: int = Field(default=os.getenv("TRIBUTE_WEBHOOK_PORT", 8081))
    TRIBUTE_BASIC_PLAN_NAME: str = os.getenv("TRIBUTE_BASIC_PLAN_NAME", "Basic")
    TRIBUTE_PREMIUM_PLAN_NAME: str = os.getenv("TRIBUTE_PREMIUM_PLAN_NAME", "Premium")
    # Ссылки на страницы оплаты — копировать из Tribute Dashboard при публикации подписки
    TRIBUTE_BASIC_URL: str = os.getenv("TRIBUTE_BASIC_URL", "")
    TRIBUTE_PREMIUM_URL: str = os.getenv("TRIBUTE_PREMIUM_URL", "")

    @field_validator('TRIBUTE_WEBHOOK_PORT', mode='before')
    def parse_tribute_webhook_port(cls, value):
        if isinstance(value, str):
            return int(value)
        return value or 8081

    def _parse_inbound_configs_raw(self, raw: str) -> list[dict]:
        """Парсит строку 'id:protocol,id:protocol' и подтягивает INBOUND_{ID}_* из env."""
        result = []
        if not raw:
            return result
        for part in raw.split(","):
            part = part.strip()
            if ":" not in part:
                continue
            inbound_id_str, protocol = part.split(":", 1)
            inbound_id = int(inbound_id_str.strip())
            protocol = protocol.strip()
            params: dict = {"id": inbound_id, "protocol": protocol}
            prefix = f"INBOUND_{inbound_id}_"
            for key, val in os.environ.items():
                if key.startswith(prefix):
                    param_name = key[len(prefix):].lower()
                    params[param_name] = val
            result.append(params)
        return result

    def get_inbound_configs(self, tier: str) -> list[dict]:
        """
        Возвращает список конфигов инбаундов для заданного тарифа.

        Пример возвращаемого элемента для Reality:
          {"id": 1, "protocol": "reality", "public_key": "...", "sni": "...", ...}
        Для xhttp:
          {"id": 3, "protocol": "xhttp", "sni": "...", "path": "/", "security": "tls", ...}
        """
        raw = self.PREMIUM_INBOUNDS if tier == "premium" else self.BASIC_INBOUNDS
        return self._parse_inbound_configs_raw(raw)

    def get_temp_inbound_configs(self) -> list[dict]:
        """Возвращает список конфигов временных инбаундов."""
        return self._parse_inbound_configs_raw(self.TEMP_INBOUND_CONFIGS)

    def calculate_price(self, months: int, tier: str = "basic") -> int:
        """Вычисляет итоговую стоимость с учётом скидки и тарифа."""
        if months not in self.PRICES:
            return 0
        price_info = self.PRICES[months]
        base_price = price_info["base_price"]
        discount_percent = price_info["discount_percent"]
        discount_amount = (base_price * discount_percent) // 100
        basic_price = base_price - discount_amount
        if tier == "premium":
            return int(basic_price * self.PREMIUM_PRICE_MULTIPLIER)
        return basic_price

    def has_premium_inbounds(self) -> bool:
        """Возвращает True, если настроены отдельные инбаунды для premium."""
        return bool(self.PREMIUM_INBOUNDS)


config = Config(
    ADMINS=os.getenv("ADMINS", ""),
)
