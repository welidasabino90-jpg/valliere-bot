"""Create the requested entry, history, and homes without replacing channels."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from ..models import ActorKind, ChannelKind
from .homes import all_homes, home_residents, normalized

logger = logging.getLogger("valliere")
BOOK_URL = "https://github.com/welidasabino90-jpg/valliere-bot/blob/main/HISTORIA.md"
BOOK_MARKER = "[VALLIERE-LIVRO-ZERO-V1]"
ENTRY_MARKER = "[VALLIERE-ENTRADA-V1]"


async def ensure_server_spaces(guild, bot, store, classify_channel) -> None:
    """Create only missing spaces, keep existing rooms and character positions."""
    import discord

    start = next((c for c in guild.categories if
                  "start" in normalized(c.name) or normalized(c.name).startswith("01 ")), None)
    if start is None:
        start = await guild.create_category("01・START", reason="Entrada do VALLIÈRE")

    async def channel_in(category, name, *, topic=""):
        channel = next((c for c in category.text_channels if c.name == name), None)
        if channel is None:
            channel = await guild.create_text_channel(
                name, category=category, topic=topic,
                reason="Preparar a entrada e a história de VALLIÈRE",
            )
        return channel

    entrance = await channel_in(start, "bem-vindos")
    book_channel = await channel_in(start, "historia")
    if ENTRY_MARKER not in (entrance.topic or ""):
        await entrance.send(
            "**Bem-vinda(o) a VALLIÈRE | Life, Fame & Secrets.**\n"
            "Esta é uma cidade viva: escolha onde ir e escreva livremente o que "
            "seu personagem faz ou diz. Comece lendo o Livro Zero em "
            f"{book_channel.mention}. Depois, siga para a cidade; não há roteiro "
            "obrigatório.\n"
            "Para telefonar use `/celular`; para enviar texto use `/mensagem`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await entrance.edit(topic=f"Entrada de VALLIÈRE. Leia #{book_channel.name}. {ENTRY_MARKER}")
    if BOOK_MARKER not in (book_channel.topic or ""):
        novel = Path(__file__).resolve().parents[3] / "HISTORIA.md"
        kwargs = {"file": discord.File(str(novel), filename="LIVRO_ZERO.txt")} if novel.is_file() else {}
        await book_channel.send(
            "**VALLIÈRE — LIVRO ZERO: ANTES DE TUDO**\n"
            "Leia a história completa no arquivo anexado ou no link: "
            f"{BOOK_URL}\nA próxima página pertence às jogadoras.",
            allowed_mentions=discord.AllowedMentions.none(), **kwargs,
        )
        await book_channel.edit(topic=f"Livro Zero de VALLIÈRE. {BOOK_MARKER}")
    # Discord's native join notification posts in the designated system channel.
    # Do not request the privileged Members intent merely to welcome a new user.
    me = guild.me
    if me and me.guild_permissions.manage_guild:
        flags = guild.system_channel_flags
        if guild.system_channel != entrance or not flags.join_notifications:
            flags.join_notifications = True
            await guild.edit(system_channel=entrance, system_channel_flags=flags,
                             reason="Mostrar a entrada quando alguém entrar no servidor")

    characters = tuple(c for c in await store.list_characters() if c.actor_kind == ActorKind.AI)
    names = {c.character_id: c.display_name for c in characters}
    for home in all_homes(tuple(names)):
        residents = home_residents(home)
        title = ("Família de Céline" if home == "família-céline" else
                 "Família Laurent" if home == "família-laurent" else names[home])
        label = f"RESIDÊNCIA — {title}"
        category = next((c for c in guild.categories if normalized(c.name) == normalized(label)), None)
        if category is None:
            category = await guild.create_category(label, reason="Moradia dos NPCs de VALLIÈRE")
        await channel_in(category, "sala")
        for resident_id in residents:
            room_name = f"quarto-{resident_id}" if len(residents) > 1 else "quarto"
            bedroom = await channel_in(category, room_name)
            person = next(c for c in characters if c.character_id == resident_id)
            if not person.residence_location_key:
                location = classify_channel(
                    guild_id=guild.id, channel_id=bedroom.id,
                    category_id=category.id, category_name=category.name,
                    channel_name=bedroom.name,
                )
                if location.kind == ChannelKind.PHYSICAL:
                    await store.save_character(replace(person, residence_location_key=location.location_key))
    logger.info("Entrada, livro e %d residências verificados.", len(all_homes(tuple(names))))
