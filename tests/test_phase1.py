from __future__ import annotations

import asyncio
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valliere.catalog import initial_characters
from valliere.map import classify_channel
from valliere.models import ActorKind, ChannelKind, CityStatus, DayPeriod, Location
from valliere.services.webhooks import WebhookError, WebhookService
from valliere.services.world import DomainError, WorldService
from valliere.stores.memory import MemoryStore


def run(coro):
    return asyncio.run(coro)


class MapTests(unittest.TestCase):
    def classify(self, category: str, channel: str) -> Location:
        return classify_channel(
            guild_id=1,
            channel_id=2,
            category_id=3,
            category_name=category,
            channel_name=channel,
        )

    def test_physical_rooms_remain_separate(self):
        reception = self.classify("03・NYX AGENCY & ATELIER", "recepção")
        casting = replace(reception, channel_id=4, channel_name="casting", room="casting")
        self.assertEqual(reception.kind, ChannelKind.PHYSICAL)
        self.assertEqual(reception.building, casting.building)
        self.assertNotEqual(reception.location_key, casting.location_key)

    def test_digital_and_admin_channels(self):
        social = self.classify("06・VALLIÈRE ONLINE", "social")
        rules = self.classify("01・START", "regras")
        self.assertEqual(social.kind, ChannelKind.DIGITAL)
        self.assertEqual(rules.kind, ChannelKind.ADMINISTRATIVE)


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.service = WorldService(self.store, guild_id=99)
        run(self.service.initialize(celine_user_id=100, emma_user_id=101, briana_user_id=102))

    def test_wake_advance_and_sleep_are_persistent(self):
        morning = run(self.service.wake_city())
        self.assertEqual(morning.city_status, CityStatus.ACTIVE)
        self.assertEqual(morning.narrative_day, 1)
        self.assertEqual(morning.day_label, "SEGUNDA-FEIRA")
        self.assertEqual(morning.period, DayPeriod.MORNING)
        afternoon = run(self.service.advance_time())
        self.assertEqual(afternoon.period, DayPeriod.AFTERNOON)
        sleeping = run(self.service.sleep_city())
        self.assertEqual(sleeping.city_status, CityStatus.SLEEPING)
        self.assertEqual(run(self.store.get_world(99)), sleeping)

    def test_sleep_never_moves_or_writes_for_humans(self):
        humans_before = {
            item.character_id: item
            for item in run(self.store.list_characters())
            if item.actor_kind == ActorKind.HUMAN
        }
        run(self.service.wake_city())
        run(self.service.sleep_city())
        humans_after = {
            item.character_id: item
            for item in run(self.store.list_characters())
            if item.actor_kind == ActorKind.HUMAN
        }
        self.assertEqual(humans_before, humans_after)

    def test_status_does_not_reveal_character_locations(self):
        location = classify_channel(
            guild_id=99,
            channel_id=88,
            category_id=7,
            category_name="03・NYX AGENCY & ATELIER",
            channel_name="recepção",
        )
        run(self.service.sync_map((location,)))
        snapshot = run(self.service.status())
        serialized = repr(snapshot)
        for character in initial_characters():
            self.assertNotIn(character.display_name, serialized)

    def test_cannot_advance_sleeping_city(self):
        with self.assertRaises(DomainError):
            run(self.service.advance_time())


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.location = classify_channel(
            guild_id=1,
            channel_id=2,
            category_id=3,
            category_name="04・NOIR",
            channel_name="bar",
        )

    def test_ai_gets_individual_identity(self):
        ai = next(item for item in initial_characters() if item.character_id == "matteo-ricci")
        payload = WebhookService.build_payload(ai, self.location, "Boa noite.")
        self.assertEqual(payload.username, "Matteo Ricci")
        self.assertEqual(payload.content, "Boa noite.")

    def test_human_generation_is_blocked(self):
        human = next(item for item in initial_characters() if item.character_id == "celine")
        with self.assertRaises(WebhookError):
            WebhookService.build_payload(human, self.location, "Texto proibido")


if __name__ == "__main__":
    unittest.main()
