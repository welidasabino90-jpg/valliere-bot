import asyncio
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from valliere.catalog import initial_characters
from valliere.models import ChannelKind, Location, WorldState
from valliere.services.ai import AIError, GeminiService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class GeminiTests(unittest.TestCase):
    def test_autonomous_action_rejects_unknown_destination(self):
        olivia = next(c for c in initial_characters() if c.character_id == "olivia-bennett")
        reception = Location(1, 2, None, "NYX", "recepção", ChannelKind.PHYSICAL,
                             building="NYX", room="recepção")
        office = Location(1, 3, None, "NYX", "sala da CEO", ChannelKind.PHYSICAL,
                          building="NYX", room="sala da CEO")
        service = GeminiService("fake-key", "gemini-3.5-flash-lite")
        with patch.object(service, "_request", return_value='{"action":"move","destination":3,"text":"Cheguei."}'):
            self.assertEqual(asyncio.run(service.decide_activity(
                character=olivia, location=reception, destinations=(office,), world=WorldState(1)
            )), ("move", 3, "Cheguei."))
        with patch.object(service, "_request", return_value='{"action":"move","destination":999,"text":"Cheguei."}'):
            with self.assertRaises(AIError):
                asyncio.run(service.decide_activity(
                    character=olivia, location=reception, destinations=(office,), world=WorldState(1)
                ))

    def test_gemini_uses_character_context_and_parses_reply(self):
        olivia = next(c for c in initial_characters() if c.character_id == "olivia-bennett")
        location = Location(1, 2, None, "NYX", "recepção", ChannelKind.PHYSICAL,
                            building="NYX", room="recepção")
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": "Bom dia, Céline."}]}}]})

        with patch("valliere.services.ai.urllib.request.urlopen", side_effect=fake_urlopen):
            reply = asyncio.run(GeminiService("fake-key", "gemini-3.5-flash-lite").reply(
                character=olivia, location=location, world=WorldState(1),
                human_name="Céline", human_message="Bom dia, Olivia",
            ))
        self.assertEqual(reply, "Bom dia, Céline.")
        self.assertEqual(requests[0].get_header("X-goog-api-key"), "fake-key")
        self.assertIn("gemini-3.5-flash-lite:generateContent", requests[0].full_url)
        instruction = json.loads(requests[0].data)["system_instruction"]["parts"][0]["text"]
        self.assertIn("confiança pessoal", instruction)
        self.assertIn("Não invente tarefas concluídas", instruction)
        self.assertIn("Nunca confirme uma ação que o sistema não executou", instruction)
        user_text = json.loads(requests[0].data)["contents"][0]["parts"][0]["text"]
        self.assertIn("MENSAGEM MAIS RECENTE DE Céline", user_text)

    def test_gemini_error_does_not_include_raw_body(self):
        raw = b'{"error":{"status":"PERMISSION_DENIED","message":"private detail"}}'
        error = urllib.error.HTTPError("url", 403, "Forbidden", {}, io.BytesIO(raw))
        with patch("valliere.services.ai.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(AIError) as caught:
                GeminiService("fake-key", "gemini-3.5-flash-lite")._request("system", "user")
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.error_code, "PERMISSION_DENIED")
        self.assertNotIn("private detail", str(caught.exception))
