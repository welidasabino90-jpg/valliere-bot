from __future__ import annotations

from dataclasses import replace

from ..catalog import initial_characters
from ..models import ActorKind, ChannelKind, CityStatus, DayPeriod, Location, StatusSnapshot, WorldState
from ..store import ValliereStore


WEEKDAYS = (
    "SEGUNDA-FEIRA",
    "TERÇA-FEIRA",
    "QUARTA-FEIRA",
    "QUINTA-FEIRA",
    "SEXTA-FEIRA",
    "SÁBADO",
    "DOMINGO",
)


class DomainError(RuntimeError):
    pass


class WorldService:
    def __init__(self, store: ValliereStore, guild_id: int) -> None:
        self.store = store
        self.guild_id = guild_id

    async def initialize(
        self,
        *,
        celine_user_id: int | None = None,
        emma_user_id: int | None = None,
        briana_user_id: int | None = None,
    ) -> WorldState:
        world = await self.store.initialize_world(WorldState(guild_id=self.guild_id))
        await self.store.upsert_characters(
            initial_characters(celine_user_id, emma_user_id, briana_user_id)
        )
        return world

    async def world(self) -> WorldState:
        state = await self.store.get_world(self.guild_id)
        if state is None:
            raise DomainError("O estado de VALLIÈRE ainda não foi inicializado.")
        return state

    async def seed_ai_locations(self) -> None:
        """Posiciona apenas IAs ainda sem localização, sem mover personagens já em jogo."""
        locations = await self.store.list_locations(self.guild_id)
        by_room = {item.channel_name.casefold(): item for item in locations if item.kind == ChannelKind.PHYSICAL}
        preferred = {
            "olivia-bennett": "recepção",
            "noah-carter": "casting",
            "camille-moreau": "lounge",
            "theo-beaumont": "atelier",
            "gabriel-torres": "entrada",
            "matteo-ricci": "escritório-matteo",
            "sofia-bellini": "bar",
        }
        for character in await self.store.list_characters():
            if character.actor_kind != ActorKind.AI or character.current_location_key:
                continue
            room = preferred.get(character.character_id)
            location = by_room.get(room.casefold()) if room else None
            if location is None:
                continue
            await self.store.save_character(
                replace(character, current_location_key=location.location_key, activity="rotina")
            )

    async def sync_map(self, locations: tuple[Location, ...]) -> None:
        if any(location.guild_id != self.guild_id for location in locations):
            raise DomainError("O mapa contém um canal de outro servidor.")
        await self.store.upsert_locations(locations)

    async def wake_city(self) -> WorldState:
        state = await self.world()
        if state.city_status == CityStatus.ACTIVE:
            raise DomainError("VALLIÈRE já está acordada.")
        next_day = (
            state.narrative_day
            if state.day_label == "ANTES DO INÍCIO"
            else state.narrative_day + 1
        )
        state = state.evolved(
            narrative_day=next_day,
            day_label=WEEKDAYS[(next_day - 1) % len(WEEKDAYS)],
            period=DayPeriod.MORNING,
            city_status=CityStatus.ACTIVE,
        )
        await self.store.save_world(state)
        return state

    async def advance_time(self) -> WorldState:
        state = await self.world()
        if state.city_status != CityStatus.ACTIVE:
            raise DomainError("A cidade está dormindo. Use /cidadeacorda primeiro.")
        if state.period == DayPeriod.LATE_NIGHT:
            raise DomainError("A madrugada chegou. Encerre o dia com /cidadedorme.")
        state = state.evolved(period=state.period.next())
        await self.store.save_world(state)
        return state

    async def sleep_city(self) -> WorldState:
        state = await self.world()
        if state.city_status == CityStatus.SLEEPING:
            raise DomainError("VALLIÈRE já está dormindo.")
        state = state.evolved(period=DayPeriod.LATE_NIGHT, city_status=CityStatus.SLEEPING)
        await self.store.save_world(state)

        # Somente IAs têm sua rotina encerrada automaticamente. As três humanas
        # permanecem integralmente sob controle de suas jogadoras.
        for character in await self.store.list_characters():
            if character.actor_kind != ActorKind.AI:
                continue
            destination = character.residence_location_key or character.current_location_key
            await self.store.save_character(
                replace(
                    character,
                    current_location_key=destination,
                    activity="descanso noturno",
                )
            )
        return state

    async def set_weather(self, weather: str) -> WorldState:
        cleaned = " ".join(weather.split())[:80]
        if not cleaned:
            raise DomainError("Informe um clima válido.")
        state = (await self.world()).evolved(weather=cleaned)
        await self.store.save_world(state)
        return state

    async def status(self) -> StatusSnapshot:
        state = await self.world()
        locations = await self.store.list_locations(self.guild_id)
        statuses: list[tuple[str, str]] = []
        seen: set[str] = set()
        for location in sorted(locations, key=lambda item: (item.building or "", item.channel_name)):
            if location.kind != ChannelKind.PHYSICAL or not location.building:
                continue
            if location.building in seen:
                continue
            seen.add(location.building)
            statuses.append((location.building, self._building_status(location.building, state)))
        # Deliberadamente não inclui localizações de personagens.
        return StatusSnapshot(state, tuple(statuses))

    @staticmethod
    def _building_status(building: str, state: WorldState) -> str:
        if state.city_status == CityStatus.SLEEPING:
            return "fechado/descanso"
        name = building.casefold()
        if "resid" in name:
            return "privado"
        if "nyx" in name:
            return "aberta" if state.period in (DayPeriod.MORNING, DayPeriod.AFTERNOON) else "fechada"
        if "noir" in name:
            return "aberto" if state.period in (DayPeriod.NIGHT, DayPeriod.LATE_NIGHT) else "fechado"
        if "evento" in name:
            return "conforme programação"
        return "em funcionamento"
