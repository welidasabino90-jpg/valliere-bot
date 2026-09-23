from __future__ import annotations

import re
import unicodedata

from .models import ChannelKind, Location


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def classify_channel(
    *,
    guild_id: int,
    channel_id: int,
    category_id: int | None,
    category_name: str,
    channel_name: str,
) -> Location:
    category = _plain(category_name)
    channel = _plain(channel_name)

    if "valliere online" in category or category.startswith("06 "):
        kind = ChannelKind.DIGITAL
    elif "evento atual" in channel:
        kind = ChannelKind.PHYSICAL
    elif any(marker in category for marker in ("start", "servicos")) or category.startswith(
        ("01 ", "08 ")
    ):
        kind = ChannelKind.ADMINISTRATIVE
    elif "eventos" in category or category.startswith("07 "):
        kind = ChannelKind.DIGITAL
    elif any(
        marker in category
        for marker in ("nyx", "noir", "residencia", "valliere")
    ) or category.startswith(("02 ", "03 ", "04 ", "05 ")):
        kind = ChannelKind.PHYSICAL
    else:
        kind = ChannelKind.ADMINISTRATIVE

    building = None
    if kind == ChannelKind.PHYSICAL:
        if "nyx" in category:
            building = "NYX Agency & Atelier"
        elif "noir" in category:
            building = "NOIR"
        elif "residencia" in category:
            building = category_name
        elif "evento atual" in channel:
            building = "Evento atual"
        else:
            building = "VALLIÈRE"

    return Location(
        guild_id=guild_id,
        channel_id=channel_id,
        category_id=category_id,
        category_name=category_name,
        channel_name=channel_name,
        kind=kind,
        building=building,
        room=channel_name if kind == ChannelKind.PHYSICAL else None,
    )

