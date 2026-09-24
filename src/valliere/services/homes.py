"""Shared homes from Book Zero and individual residences of other NPCs."""

from __future__ import annotations

import unicodedata


FAMILY_HOMES = {
    "família-céline": ("vivienne", "charles", "camille"),
    "família-laurent": ("helena-laurent", "arthur-laurent", "liam-laurent", "amelie-laurent"),
}


def home_name(character_id: str) -> str:
    for name, residents in FAMILY_HOMES.items():
        if character_id in residents:
            return name
    return character_id


def home_residents(name: str) -> tuple[str, ...]:
    return FAMILY_HOMES.get(name, (name,))


def all_homes(npc_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(home_name(npc_id) for npc_id in npc_ids))


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c))


def residence_name(building: str | None) -> str | None:
    """Returns a private home's owner key based on its Discord category."""
    name = normalized(building or "")
    if "residencia" not in name:
        return None
    if "emma" in name and "briana" in name:
        return "humanas-emma-briana"
    if "familia" in name and "celine" in name:
        return "família-céline"
    if "laurent" in name:
        return "família-laurent"
    if "celine" in name and "familia" not in name:
        return "humana-celine"
    for npc_id in NPC_HOME_IDS:
        if normalized(npc_id).replace("-", " ") in name:
            return npc_id
    return "unknown-residence"


NPC_HOME_IDS = (
    "nathan", "olivia-bennett", "noah-carter", "camille-moreau",
    "theo-beaumont", "gabriel-torres", "matteo-ricci", "sofia-bellini",
    "luca-moretti", "kiara-bennett", "maya-collins", "ryan-blake",
)


def owns_home(character_id: str, building: str | None) -> bool:
    return residence_name(building) == home_name(character_id)


def may_visit_home(character_id: str, building: str | None, *,
                   invited_by_resident: bool = False) -> bool:
    home = residence_name(building)
    return home is None or home == home_name(character_id) or invited_by_resident
