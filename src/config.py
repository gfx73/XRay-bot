from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from models import SubscriptionTier


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    ADMINS: list[int] = Field(default_factory=list)
    XUI_API_URL: str = "http://localhost:54321"
    XUI_BASE_PATH: str = "/panel"
    XUI_SUB_PORT: str = "54321"
    XUI_API_TOKEN: str = ""
    XUI_VERIFY_SSL: bool = True
    PAYMENT_TOKEN: str = ""

    STANDARD_INBOUNDS: str = ""
    PREMIUM_INBOUNDS: str = ""

    PREMIUM_TRAFFIC_LIMIT_GB: int = 0
    STANDARD_TRAFFIC_LIMIT_GB: int = 0
    STANDARD_IP_LIMIT: int = 0
    PREMIUM_IP_LIMIT: int = 0

    TRIAL_DAYS: int = 3
    TRIAL_TIER: str = "standard"

    PREMIUM_PRICE_MULTIPLIER: float = 1.5

    PRICES: dict[int, dict[str, int]] = {
        1: {"base_price": 100, "discount_percent": 0},
        3: {"base_price": 300, "discount_percent": 10},
        6: {"base_price": 600, "discount_percent": 20},
        12: {"base_price": 1200, "discount_percent": 30},
    }

    SUBSCRIPTION_URL_BASE: str = ""
    SUB_BASE_PATH: str = "sub"

    TRIBUTE_API_KEY: str = ""
    TRIBUTE_WEBHOOK_PORT: int = 8081
    TRIBUTE_BASIC_PLAN_NAME: str = "Basic"
    TRIBUTE_PREMIUM_PLAN_NAME: str = "Premium"
    TRIBUTE_BASIC_URL: str = ""
    TRIBUTE_PREMIUM_URL: str = ""

    @field_validator("ADMINS", mode="before")
    @classmethod
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(a) for a in value.split(",") if a.strip()]
        return value or []

    def _parse_inbound_configs_raw(self, raw: str) -> list[dict]:
        result = []
        if not raw:
            return result
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                result.append({"id": int(part)})
        return result

    def get_inbound_configs(self, tier: SubscriptionTier) -> list[dict]:
        raw = self.PREMIUM_INBOUNDS if tier == SubscriptionTier.PREMIUM else self.STANDARD_INBOUNDS
        return self._parse_inbound_configs_raw(raw)

    def calculate_price(self, months: int, tier: SubscriptionTier = SubscriptionTier.STANDARD) -> int:
        if months not in self.PRICES:
            return 0
        price_info = self.PRICES[months]
        base_price = price_info["base_price"]
        discount_amount = (base_price * price_info["discount_percent"]) // 100
        basic_price = base_price - discount_amount
        if tier == SubscriptionTier.PREMIUM:
            return int(basic_price * self.PREMIUM_PRICE_MULTIPLIER)
        return basic_price

    def has_premium_inbounds(self) -> bool:
        return bool(self.PREMIUM_INBOUNDS)


config = Config()
