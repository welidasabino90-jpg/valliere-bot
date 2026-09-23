from __future__ import annotations

import asyncio
from typing import Any

from ..models import (
    ActorKind,
    ChannelKind,
    Character,
    CityStatus,
    DayPeriod,
    Location,
    WorldState,
)


class SupabaseStore:
    """Persistência real. O cliente síncrono é isolado com asyncio.to_thread."""

    def __init__(self, url: str, service_role_key: str) -> None:
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError(
                "Instale as dependências com: pip install -r requirements.txt"
            ) from exc

        self.client = create_client(url, service_role_key)

    async def _run(self, fn: Any) -> Any:
        return await asyncio.to_thread(fn)

    async def initialize_world(self, default: WorldState) -> WorldState:
        existing = await self.get_world(default.guild_id)

        if existing:
            return existing

        await self.save_world(default)
        return default

    async def get_world(self, guild_id: int) -> WorldState | None:
        response = await self._run(
            lambda: self.client.table("world_states")
            .select("*")
            .eq("guild_id", guild_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            return None

        row = rows[0]

        return WorldState(
            guild_id=int(row["guild_id"]),
            narrative_day=int(row["narrative_day"]),
            day_label=row["day_label"],
            period=DayPeriod(row["period"]),
            city_status=CityStatus(row["city_status"]),
            weather=row["weather"],
        )

    async def save_world(self, state: WorldState) -> None:
        payload = {
            "guild_id": state.guild_id,
            "narrative_day": state.narrative_day,
            "day_label": state.day_label,
            "period": state.period.value,
            "city_status": state.city_status.value,
            "weather": state.weather,
        }

        await self._run(
            lambda: self.client.table("world_states")
            .upsert(payload)
            .execute()
        )

    async def upsert_locations(
        self,
        locations: tuple[Location, ...],
    ) -> None:
        if not locations:
            return

        payload = [
            {
                "guild_id": item.guild_id,
                "channel_id": item.channel_id,
                "category_id": item.category_id,
                "category_name": item.category_name,
                "channel_name": item.channel_name,
                "kind": item.kind.value,
                "building": item.building,
                "room": item.room,
                "metadata": item.metadata,
            }
            for item in locations
        ]

        await self._run(
            lambda: self.client.table("locations")
            .upsert(payload)
            .execute()
        )

    async def list_locations(
        self,
        guild_id: int,
    ) -> tuple[Location, ...]:
        response = await self._run(
            lambda: self.client.table("locations")
            .select("*")
            .eq("guild_id", guild_id)
            .execute()
        )

        rows = response.data or []

        return tuple(
            Location(
                guild_id=int(row["guild_id"]),
                channel_id=int(row["channel_id"]),
                category_id=(
                    int(row["category_id"])
                    if row.get("category_id")
                    else None
                ),
                category_name=row["category_name"],
                channel_name=row["channel_name"],
                kind=ChannelKind(row["kind"]),
                building=row.get("building"),
                room=row.get("room"),
                metadata=row.get("metadata") or {},
            )
            for row in rows
        )

    async def upsert_characters(
        self,
        characters: tuple[Character, ...],
    ) -> None:
        if not characters:
            return

        # A localização/atividade existente não é apagada
        # durante a inicialização.
        for character in characters:
            response = await self._run(
                lambda character_id=character.character_id:
                self.client.table("characters")
                .select("character_id")
                .eq("character_id", character_id)
                .limit(1)
                .execute()
            )

            rows = response.data or []

            if rows:
                continue

            await self.save_character(character)

    async def list_characters(
        self,
    ) -> tuple[Character, ...]:
        response = await self._run(
            lambda: self.client.table("characters")
            .select("*")
            .execute()
        )

        rows = response.data or []

        return tuple(
            self._character_from_row(row)
            for row in rows
        )

    async def save_character(
        self,
        character: Character,
    ) -> None:
        payload = {
            "character_id": character.character_id,
            "display_name": character.display_name,
            "actor_kind": character.actor_kind.value,
            "controller_discord_user_id":
                character.controller_discord_user_id,
            "avatar_url": character.avatar_url,
            "residence_location_key":
                character.residence_location_key,
            "current_location_key":
                character.current_location_key,
            "activity": character.activity,
            "profile": character.profile,
        }

        await self._run(
            lambda: self.client.table("characters")
            .upsert(payload)
            .execute()
        )

    async def get_character(self, character_id: str) -> Character | None:
        response = await self._run(
            lambda: self.client.table("characters")
            .select("*").eq("character_id", character_id).limit(1).execute()
        )
        rows = response.data or []
        return self._character_from_row(rows[0]) if rows else None

    async def memories_for(self, guild_id: int, character_id: str, limit: int = 8) -> tuple[str, ...]:
        response = await self._run(
            lambda: self.client.table("memories")
            .select("content").eq("guild_id", guild_id)
            .eq("character_id", character_id)
            .order("created_at", desc=True).limit(limit).execute()
        )
        return tuple(row["content"] for row in reversed(response.data or []))

    async def add_memory(
        self,
        guild_id: int,
        character_id: str,
        content: str,
        *,
        source_character_id: str | None = None,
        location_key: str | None = None,
        kind: str = "conversa",
        importance: int = 1,
    ) -> None:
        payload = {
            "guild_id": guild_id,
            "character_id": character_id,
            "kind": kind,
            "content": content[:1000],
            "source_character_id": source_character_id,
            "location_key": location_key,
            "importance": max(1, min(5, importance)),
        }
        await self._run(lambda: self.client.table("memories").insert(payload).execute())

    @staticmethod
    def _character_from_row(
        row: dict[str, Any],
    ) -> Character:
        return Character(
            character_id=row["character_id"],
            display_name=row["display_name"],
            actor_kind=ActorKind(row["actor_kind"]),
            controller_discord_user_id=(
                int(row["controller_discord_user_id"])
                if row.get("controller_discord_user_id")
                else None
            ),
            avatar_url=row.get("avatar_url"),
            residence_location_key=row.get(
                "residence_location_key"
            ),
            current_location_key=row.get(
                "current_location_key"
            ),
            activity=row.get("activity") or "indefinida",
            profile=row.get("profile") or {},
        )

