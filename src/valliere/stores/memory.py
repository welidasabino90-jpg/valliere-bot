from __future__ import annotations

from dataclasses import replace

from ..models import Character, Location, WorldState


class MemoryStore:
    """Store determinístico para testes; não é usado como persistência de produção."""

    def __init__(self) -> None:
        self.worlds: dict[int, WorldState] = {}
        self.locations: dict[tuple[int, int], Location] = {}
        self.characters: dict[str, Character] = {}

    async def initialize_world(self, default: WorldState) -> WorldState:
        self.worlds.setdefault(default.guild_id, default)
        return self.worlds[default.guild_id]

    async def get_world(self, guild_id: int) -> WorldState | None:
        return self.worlds.get(guild_id)

    async def save_world(self, state: WorldState) -> None:
        self.worlds[state.guild_id] = replace(state)

    async def upsert_locations(self, locations: tuple[Location, ...]) -> None:
        for location in locations:
            self.locations[(location.guild_id, location.channel_id)] = location

    async def list_locations(self, guild_id: int) -> tuple[Location, ...]:
        return tuple(
            location
            for (stored_guild_id, _), location in self.locations.items()
            if stored_guild_id == guild_id
        )

    async def upsert_characters(self, characters: tuple[Character, ...]) -> None:
        for character in characters:
            self.characters.setdefault(character.character_id, character)

    async def list_characters(self) -> tuple[Character, ...]:
        return tuple(self.characters.values())

    async def save_character(self, character: Character) -> None:
        self.characters[character.character_id] = character

