from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class CityStatus(StrEnum):
    ACTIVE = "ATIVA"
    SLEEPING = "DORMINDO"


class DayPeriod(StrEnum):
    MORNING = "MANHÃ"
    AFTERNOON = "TARDE"
    NIGHT = "NOITE"
    LATE_NIGHT = "MADRUGADA"

    def next(self) -> "DayPeriod":
        order = list(type(self))
        return order[(order.index(self) + 1) % len(order)]


class ChannelKind(StrEnum):
    PHYSICAL = "FISICO"
    DIGITAL = "DIGITAL"
    ADMINISTRATIVE = "ADMINISTRATIVO"


class ActorKind(StrEnum):
    HUMAN = "HUMANO"
    AI = "IA"


@dataclass(frozen=True, slots=True)
class WorldState:
    guild_id: int
    narrative_day: int = 1
    day_label: str = "ANTES DO INÍCIO"
    period: DayPeriod = DayPeriod.MORNING
    city_status: CityStatus = CityStatus.SLEEPING
    weather: str = "céu parcialmente nublado"

    def evolved(self, **changes: Any) -> "WorldState":
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class Location:
    guild_id: int
    channel_id: int
    category_id: int | None
    category_name: str
    channel_name: str
    kind: ChannelKind
    building: str | None = None
    room: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def location_key(self) -> str:
        return f"discord:{self.guild_id}:{self.channel_id}"


@dataclass(frozen=True, slots=True)
class Character:
    character_id: str
    display_name: str
    actor_kind: ActorKind
    controller_discord_user_id: int | None = None
    avatar_url: str | None = None
    residence_location_key: str | None = None
    current_location_key: str | None = None
    activity: str = "indefinida"
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    world: WorldState
    location_statuses: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class WebhookPayload:
    character_id: str
    username: str
    avatar_url: str | None
    content: str
