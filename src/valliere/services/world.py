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
        await self._start_workday(state)
        return state

    async def _start_workday(self, state: WorldState) -> None:
        if state.day_label in ("SÁBADO", "DOMINGO"):
            return
        locations = await self.store.list_locations(self.guild_id)
        agency = [place for place in locations if place.kind == ChannelKind.PHYSICAL
                  and place.building == "NYX Agency & Atelier"]
        shifts = {
            "olivia-bennett": "recepção",
            "noah-carter": "casting",
            "camille-moreau": "lounge",
            "theo-beaumont": "atelier",
            "gabriel-torres": "entrada",
        }
        for person in await self.store.list_characters():
            room = shifts.get(person.character_id)
            if person.actor_kind != ActorKind.AI or not room:
                continue
            destination = next((place for place in agency if room in (place.room or "").casefold()), None)
            if destination and person.current_location_key != destination.location_key:
                await self.store.save_character(replace(
                    person, current_location_key=destination.location_key,
                    activity=f"trabalhando em {destination.room}",
                ))

    async def advance_time(self) -> WorldState:
        state = await self.world()
        if state.city_status != CityStatus.ACTIVE:
            raise DomainError("A cidade está dormindo. Use /cidadeacorda primeiro.")
        if state.period == DayPeriod.LATE_NIGHT:
            raise DomainError("A madrugada chegou. Encerre o dia com /cidadedorme.")
        state = state.evolved(period=state.period.next())
        await self.store.save_world(state)
        if state.period == DayPeriod.NIGHT:
            locations = await self.store.list_locations(self.guild_id)
            noir = [place for place in locations if place.kind == ChannelKind.PHYSICAL
                    and place.building == "NOIR"]
            for person in await self.store.list_characters():
                if person.character_id not in ("matteo-ricci", "sofia-bellini"):
                    continue
                room = "escritório" if person.character_id == "matteo-ricci" else "bar"
                destination = next((place for place in noir if room in (place.room or "").casefold()), None)
                if destination and person.current_location_key != destination.location_key:
                    await self.store.save_character(replace(
                        person, current_location_key=destination.location_key,
                        activity=f"trabalhando em {destination.room}",
                    ))
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
