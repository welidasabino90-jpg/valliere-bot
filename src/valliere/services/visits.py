"""Rules for an NPC entering a private home after being addressed remotely."""

import re


def may_enter_from_message(building: str | None, spoken_text: str) -> bool:
    """Naming an NPC in a residence is not an invitation into that residence."""
    if "resid" not in (building or "").casefold():
        return True
    speech = spoken_text.casefold()
    invitation = re.search(r"\b(?:venha|vem|passe|entre|entra|visite)\b", speech)
    home = re.search(r"\b(?:aqui|em casa|na minha casa|neste quarto|no meu quarto|na residência|na residencia)\b", speech)
    return bool(invitation and home)
