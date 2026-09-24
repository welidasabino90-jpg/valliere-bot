"""Resolve NPCs for remote contact without silently guessing a namesake."""

from ..models import ActorKind
from .homes import normalized


def find_contact(characters, entered_name: str):
    wanted = normalized(entered_name.strip())
    npcs = [c for c in characters if c.actor_kind == ActorKind.AI]
    exact = [c for c in npcs if normalized(c.character_id) == wanted
             or normalized(c.display_name) == wanted]
    if len(exact) == 1:
        return exact[0]
    first = [c for c in npcs if normalized(c.display_name.split()[0]) == wanted]
    return first[0] if len(first) == 1 else None
