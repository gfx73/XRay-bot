from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, YamlConfigSettingsSource

from models import SubscriptionTier


class DigitalProduct(BaseModel):
    name: str
    tier: SubscriptionTier
    hours: int
    url: str = ""
    referral_reward_hours: int = 0

    @field_validator("hours")
    @classmethod
    def check_hours(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("hours must be > 0")
        return v


class TributeSub(BaseModel):
    name: str
    tier: SubscriptionTier
    url: str
    referral_reward_hours: int = 0


class Config(BaseSettings):
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
    TRIBUTE_SUBSCRIPTIONS: list[TributeSub] = Field(default_factory=list)
    TRIBUTE_DIGITAL_PRODUCTS: list[DigitalProduct] = Field(default_factory=list)

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (YamlConfigSettingsSource(settings_cls, yaml_file=Path(__file__).parent / "config.yaml"),)

    @model_validator(mode="after")
    def check_no_duplicate_names(self) -> "Config":
        product_names = [p.name for p in self.TRIBUTE_DIGITAL_PRODUCTS]
        if len(product_names) != len(set(product_names)):
            raise ValueError("TRIBUTE_DIGITAL_PRODUCTS contains duplicate product names")
        sub_names = [s.name for s in self.TRIBUTE_SUBSCRIPTIONS]
        if len(sub_names) != len(set(sub_names)):
            raise ValueError("TRIBUTE_SUBSCRIPTIONS contains duplicate subscription names")
        return self

    def _parse_inbound_configs_raw(self, raw: str) -> list[dict]:
        if not raw:
            return []
        return [{"id": int(p)} for p in (s.strip() for s in raw.split(",")) if p.isdigit()]

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
