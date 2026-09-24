import unittest

from valliere.catalog import initial_characters
from valliere.models import ActorKind, ChannelKind, Location
from valliere.map import classify_channel
from valliere.services.homes import all_homes, home_name, home_residents, may_visit_home, residence_name
from valliere.services.phone import find_contact
from valliere.services.webhooks import WebhookService


class HomesAndPhoneTests(unittest.TestCase):
    def setUp(self):
        self.people = initial_characters()

    def test_family_members_share_home_without_merging_unrelated_humans(self):
        npcs = tuple(c.character_id for c in self.people if c.actor_kind == ActorKind.AI)
        self.assertEqual(len(all_homes(npcs)), 14)
        self.assertEqual(home_name("vivienne"), home_name("camille"))
        self.assertEqual(home_name("helena-laurent"), home_name("amelie-laurent"))
        self.assertNotIn("emma", home_residents("família-laurent"))
        self.assertNotIn("briana", home_residents("família-laurent"))

    def test_foreign_residence_is_closed_without_invitation(self):
        own = "RESIDÊNCIA — Olivia Bennett"
        other = "RESIDÊNCIA — Noah Carter"
        self.assertEqual(residence_name(own), "olivia-bennett")
        self.assertTrue(may_visit_home("olivia-bennett", own))
        self.assertFalse(may_visit_home("olivia-bennett", other))
        self.assertTrue(may_visit_home("olivia-bennett", other, invited_by_resident=True))
        self.assertFalse(may_visit_home("noah-carter", "05・RESIDÊNCIA — CÉLINE"))
        self.assertEqual(classify_channel(
            guild_id=1, channel_id=2, category_id=3,
            category_name=own, channel_name="quarto",
        ).kind, ChannelKind.PHYSICAL)

    def test_phone_contact_and_payload_do_not_require_colocation(self):
        olivia = find_contact(self.people, "Olivia Bennett")
        self.assertEqual(olivia.character_id, "olivia-bennett")
        self.assertEqual(find_contact(self.people, "camille-moreau").character_id, "camille-moreau")
        self.assertIsNone(find_contact(self.people, "Céline"))
        self.assertIsNone(find_contact(self.people, "desconhecida"))
        payload = WebhookService.build_phone_payload(olivia, "Bom dia!", "celular")
        self.assertTrue(payload.content.startswith("📱 **ligação**"))


if __name__ == "__main__":
    unittest.main()
