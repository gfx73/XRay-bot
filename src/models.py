from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SlotName(StrEnum):
    STANDARD = "standard"
    WL = "wl"


class InboundMeta(BaseModel):
    port: int
    remark: str


class ProfileSlot(BaseModel):
    email: str
    uuid: str
    sub_id: str
    inbound_ids: list[int] = Field(default_factory=list)
    inbounds: dict[str, InboundMeta] = Field(default_factory=dict)


class UserProfiles(BaseModel):
    standard: ProfileSlot | None = None
    wl: ProfileSlot | None = None

    def __bool__(self) -> bool:
        return self.standard is not None or self.wl is not None

    def slots(self) -> dict[SlotName, ProfileSlot]:
        result: dict[SlotName, ProfileSlot] = {}
        if self.standard is not None:
            result[SlotName.STANDARD] = self.standard
        if self.wl is not None:
            result[SlotName.WL] = self.wl
        return result
