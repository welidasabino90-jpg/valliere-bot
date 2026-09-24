import unittest

from valliere.catalog import initial_characters
from valliere.models import ActorKind
from valliere.story import PERSONAL_HISTORY, history_for
from valliere.services.visits import may_enter_from_message


class BookZeroContinuityTests(unittest.TestCase):
    def test_every_ai_inhabitant_has_private_historical_context(self):
        npc_ids = {person.character_id for person in initial_characters()
                   if person.actor_kind == ActorKind.AI}
        self.assertEqual(npc_ids, PERSONAL_HISTORY.keys())
        self.assertNotIn("celine", PERSONAL_HISTORY)
        self.assertNotIn("emma", PERSONAL_HISTORY)
        self.assertNotIn("briana", PERSONAL_HISTORY)

    def test_private_experiences_are_not_leaked_to_unrelated_cast(self):
        self.assertIn("Luca", history_for("noah-carter"))
        self.assertNotIn("pasta", history_for("noah-carter"))
        self.assertIn("pasta", history_for("olivia-bennett"))
        self.assertNotIn("pasta", history_for("helena-laurent"))
        self.assertIn("não é a irmã de Céline", history_for("camille-moreau"))
        self.assertNotIn("não é a irmã de Céline", history_for("camille"))

    def test_work_request_in_bedroom_does_not_teleport_npc(self):
        self.assertFalse(may_enter_from_message("Residência — Céline", "Noah, preciso conversar sobre casting"))
        self.assertFalse(may_enter_from_message("Residência — Céline", "Olivia, avise Noah para vir à minha sala"))
        self.assertTrue(may_enter_from_message("Residência — Céline", "Noah, venha aqui em casa"))
        self.assertTrue(may_enter_from_message("NYX Agency & Atelier", "Noah, preciso conversar sobre casting"))


if __name__ == "__main__":
    unittest.main()
