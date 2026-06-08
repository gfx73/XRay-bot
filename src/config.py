import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: list[int] = Field(default_factory=list)
    XUI_API_URL: str = os.getenv("XUI_API_URL", "http://localhost:54321")
    XUI_BASE_PATH: str = os.getenv("XUI_BASE_PATH", "/panel")
    XUI_SUB_PORT: str = os.getenv("XUI_SUB_PORT", "54321")
    XUI_API_TOKEN: str = os.getenv("XUI_API_TOKEN", "")
    XUI_VERIFY_SSL: bool = Field(default=os.getenv("XUI_VERIFY_SSL", "True").lower() == "true")
    PAYMENT_TOKEN: str = os.getenv("PAYMENT_TOKEN", "")

    # Тарифы: ID инбаундов через запятую — например "1" или "1,3"
    # Протокол берётся из панели, VLESS-ссылки — из /sub/{sub_id}
    BASIC_INBOUNDS: str = os.getenv("BASIC_INBOUNDS", "")
    PREMIUM_INBOUNDS: str = os.getenv("PREMIUM_INBOUNDS", "")

    # Лимит трафика для wl-клиента premium (в ГБ), 0 = безлимит
    PREMIUM_TRAFFIC_LIMIT_GB: int = Field(default=int(os.getenv("PREMIUM_TRAFFIC_LIMIT_GB", "0")))

    TRIAL_DAYS: int = Field(default=int(os.getenv("TRIAL_DAYS", "3")))
    TRIAL_TIER: str = os.getenv("TRIAL_TIER", "basic")

    # Коэффициент цены Premium = цена Basic * PREMIUM_PRICE_MULTIPLIER
    PREMIUM_PRICE_MULTIPLIER: float = Field(
        default=float(os.getenv("PREMIUM_PRICE_MULTIPLIER", "1.5"))
    )

    # Настройки цен и скидок
    PRICES: dict[int, dict[str, int]] = {
        1: {"base_price": 100, "discount_percent": 0},
        3: {"base_price": 300, "discount_percent": 10},
        6: {"base_price": 600, "discount_percent": 20},
        12: {"base_price": 1200, "discount_percent": 30}
    }
    SUBSCRIPTION_URL_BASE: str = os.getenv("SUBSCRIPTION_URL_BASE", "")
    SUB_BASE_PATH: str = os.getenv("SUB_BASE_PATH", "sub")

    @field_validator('ADMINS', mode='before')
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []

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
        """Парсит строку ID инбаундов через запятую: '1' или '1,3'."""
        result = []
        if not raw:
            return result
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                result.append({"id": int(part)})
        return result

    def get_inbound_configs(self, tier: str) -> list[dict]:
        """Возвращает список инбаундов для тарифа: [{"id": int, "protocol": str}, ...]."""
        raw = self.PREMIUM_INBOUNDS if tier == "premium" else self.BASIC_INBOUNDS
        return self._parse_inbound_configs_raw(raw)

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
