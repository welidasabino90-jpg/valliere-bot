from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Variável obrigatória ausente: {name}")
    return value


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} precisa ser um ID numérico.") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    discord_guild_id: int
    supabase_url: str
    supabase_service_role_key: str
    celine_user_id: int | None = None
    emma_user_id: int | None = None
    briana_user_id: int | None = None

    @property
    def authorized_human_ids(self) -> frozenset[int]:
        return frozenset(
            value
            for value in (self.celine_user_id, self.emma_user_id, self.briana_user_id)
            if value is not None
        )

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            guild_id = int(_required("DISCORD_GUILD_ID"))
        except ValueError as exc:
            raise ConfigurationError("DISCORD_GUILD_ID precisa ser numérico.") from exc
        return cls(
            discord_token=_required("DISCORD_TOKEN"),
            discord_guild_id=guild_id,
            supabase_url=_required("SUPABASE_URL"),
            supabase_service_role_key=_required("SUPABASE_SERVICE_ROLE_KEY"),
            celine_user_id=_optional_int("DISCORD_CELINE_USER_ID"),
            emma_user_id=_optional_int("DISCORD_EMMA_USER_ID"),
            briana_user_id=_optional_int("DISCORD_BRIANA_USER_ID"),
        )

