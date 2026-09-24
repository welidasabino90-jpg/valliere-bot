from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import replace

from .config import ConfigurationError, Settings

logger = logging.getLogger("valliere")


def _require_discord():
    try:
        import discord
        from discord import app_commands
        from discord.ext import commands
    except ImportError as exc:
        raise RuntimeError("Instale as dependências com: pip install -r requirements.txt") from exc
    return discord, app_commands, commands


def create_bot(settings: Settings):
    discord, app_commands, commands = _require_discord()

    from .catalog import initial_characters
    from .map import classify_channel
    from .models import ActorKind, ChannelKind, CityStatus
    from .services.ai import AIError, GeminiService, GroqService
    from .services.webhooks import WebhookService
    from .services.world import DomainError, WorldService
    from .stores.supabase import SupabaseStore

    class ValliereBot(commands.Bot):
        def __init__(self) -> None:
            intents = discord.Intents.default()
            intents.guilds = True
            intents.messages = True
            intents.message_content = True
            super().__init__(
                command_prefix=commands.when_mentioned,
                intents=intents,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self.store = SupabaseStore(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )
            self.world_service = WorldService(self.store, settings.discord_guild_id)
            self.webhook_service = WebhookService()
            self.ai_service = (
                GeminiService(settings.gemini_api_key, settings.gemini_model)
                if settings.ai_provider == "gemini"
                else GroqService(settings.groq_api_key, settings.groq_model)
            )
            self.location_by_channel: dict[int, object] = {}
            self._sleep_notice_channels: set[int] = set()
            self._active_conversations: dict[tuple[int, int], tuple[str, float]] = {}
            self._routine_task: asyncio.Task | None = None
            self._routine_lock = asyncio.Lock()
            self._npc_last_turn: dict[str, float] = {}

        async def setup_hook(self) -> None:
            await self.world_service.initialize(
                celine_user_id=settings.celine_user_id,
                emma_user_id=settings.emma_user_id,
                briana_user_id=settings.briana_user_id,
            )
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("%d comandos sincronizados no servidor %d", len(synced), guild.id)

        async def on_ready(self) -> None:
            guild = self.get_guild(settings.discord_guild_id)
            if guild is None:
                logger.error("Servidor %d não foi encontrado.", settings.discord_guild_id)
                return
            locations = tuple(
                classify_channel(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    category_id=channel.category_id,
                    category_name=channel.category.name if channel.category else "Sem categoria",
                    channel_name=channel.name,
                )
                for channel in guild.text_channels
            )
            await self.world_service.sync_map(locations)
            self.location_by_channel = {item.channel_id: item for item in locations}
            logger.info("Mapa sincronizado: %d canais reconhecidos.", len(locations))
            # Personagens recém-criados precisam de um ponto de partida para
            # participar da rotina. Nunca altera uma localização já escolhida.
            public = [place for place in locations if place.kind == ChannelKind.PHYSICAL
                      and place.building in ("NYX Agency & Atelier", "NOIR")]
            for person in await self.store.list_characters():
                if person.actor_kind != ActorKind.AI or person.current_location_key or not public:
                    continue
                profession = str(person.profile.get("profession", "")).casefold()
                preferred = ("NOIR" if "noir" in profession or "bartender" in profession
                             else "NYX Agency & Atelier")
                options = [place for place in public if place.building == preferred] or public
                room_hint = ("casting" if "casting" in profession else
                             "recepção" if "assistente" in profession else "")
                start = next((place for place in options if room_hint and room_hint in place.room.casefold()),
                             options[0])
                await self.store.save_character(replace(person, current_location_key=start.location_key,
                                                        activity=f"presente em {start.room}"))
            world = await self.world_service.world()
            if world.city_status == CityStatus.ACTIVE and world.period.value in ("MANHÃ", "TARDE"):
                reception = next((place for place in locations if place.kind == ChannelKind.PHYSICAL
                                  and place.building == "NYX Agency & Atelier"
                                  and "recepção" in (place.room or "").casefold()), None)
                if reception:
                    for person in await self.store.list_characters():
                        if person.character_id == "olivia-bennett" and person.current_location_key != reception.location_key:
                            await self.store.save_character(replace(person, current_location_key=reception.location_key,
                                                                    activity="atendendo na recepção"))
            if self._routine_task is None or self._routine_task.done():
                self._routine_task = asyncio.create_task(self._npc_routine())

        async def close(self) -> None:
            if self._routine_task:
                self._routine_task.cancel()
                try:
                    await self._routine_task
                except asyncio.CancelledError:
                    pass
            await super().close()

        async def _npc_routine(self) -> None:
            # Apenas um NPC por ciclo: limita mensagens e chamadas à IA.
            await asyncio.sleep(300)
            while not self.is_closed():
                try:
                    await self._run_npc_turn()
                except Exception:
                    logger.exception("Falha na rotina autônoma dos NPCs")
                await asyncio.sleep(300)

        async def _run_npc_turn(self) -> None:
            if self._routine_lock.locked():
                return
            async with self._routine_lock:
                await self._npc_turn()

        async def _npc_turn(self) -> None:
            if not self.ai_service.enabled:
                return
            world = await self.world_service.world()
            if world.city_status != CityStatus.ACTIVE:
                return
            locations = tuple(place for place in self.location_by_channel.values()
                              if place.kind == ChannelKind.PHYSICAL
                              and self.get_channel(place.channel_id) is not None)
            if not locations:
                return
            by_key = {place.location_key: place for place in locations}
            eligible = [person for person in await self.store.list_characters()
                        if person.actor_kind == ActorKind.AI and person.current_location_key in by_key
                        and person.profile.get("autonomy_enabled") is True]
            if not eligible:
                return
            character = min(eligible, key=lambda item: (self._npc_last_turn.get(item.character_id, 0),
                                                        random.random()))
            self._npc_last_turn[character.character_id] = time.monotonic()
            current = by_key[character.current_location_key]
            destinations = tuple(place for place in locations if place.channel_id != current.channel_id)
            if character.character_id == "olivia-bennett" and world.period.value in ("MANHÃ", "TARDE"):
                reception = next((place for place in locations if place.building == "NYX Agency & Atelier"
                                  and "recepção" in (place.room or "").casefold()), None)
                if reception and current.location_key != reception.location_key:
                    await self.store.save_character(replace(character, current_location_key=reception.location_key,
                                                            activity="atendendo na recepção"))
                    return
                destinations = ()
            if len(destinations) > 12:
                destinations = tuple(random.sample(destinations, 12))
            memory = await self.store.list_memories(character.character_id, limit=4)
            action, destination_id, speech = await self.ai_service.decide_activity(
                character=character, location=current, destinations=destinations,
                world=world, recent_memory=memory,
            )
            if action == "stay":
                return
            target = (next(place for place in destinations if place.channel_id == destination_id)
                      if action == "move" else current)
            if action == "move":
                # Um único current_location_key é gravado antes de falar no destino.
                character = replace(character, current_location_key=target.location_key,
                                    activity=f"presente em {target.room}")
                await self.store.save_character(character)
            if speech:
                channel = self.get_channel(target.channel_id)
                payload = self.webhook_service.build_payload(character, target, speech)
                await self.webhook_service.send(channel, payload)

        async def _deliver_visit(self, recipient_id: str, destination, caller_name: str) -> None:
            await asyncio.sleep(12)
            try:
                world = await self.world_service.world()
                if world.city_status != CityStatus.ACTIVE:
                    return
                recipient = next((item for item in await self.store.list_characters()
                                  if item.character_id == recipient_id and item.actor_kind == ActorKind.AI), None)
                channel = self.get_channel(destination.channel_id)
                if recipient is None or channel is None:
                    return
                recipient = replace(recipient, current_location_key=destination.location_key,
                                    activity=f"visitando {destination.room}")
                await self.store.save_character(recipient)
                self._npc_last_turn[recipient.character_id] = time.monotonic()
                memories = await self.store.list_memories(recipient.character_id, limit=4)
                try:
                    speech = await self.ai_service.reply(
                        character=recipient, location=destination, world=world,
                        human_name=caller_name,
                        human_message=f"Você recebeu um recado para vir conversar com {caller_name} nesta sala. Você acaba de chegar. Cumprimente e responda ao assunto do recado, sem alegar ter concluído outras tarefas.",
                        recent_memory=memories,
                    )
                except Exception:
                    logger.exception("Falha na fala de chegada de %s", recipient_id)
                    speech = f"Oi, {caller_name}. Recebi seu recado e vim conversar."
                await self.webhook_service.send(channel, self.webhook_service.build_payload(recipient, destination, speech))
            except Exception:
                logger.exception("Falha ao atender convite de %s", recipient_id)

        async def on_message(self, message) -> None:
            if message.author.bot or message.webhook_id or not message.guild:
                return
            location = self.location_by_channel.get(message.channel.id)
            if location is None or location.kind != ChannelKind.PHYSICAL:
                return
            state = await self.world_service.world()
            if state.city_status == CityStatus.SLEEPING:
                if message.channel.id not in self._sleep_notice_channels:
                    self._sleep_notice_channels.add(message.channel.id)
                    await message.channel.send(
                        "🌙 **A cidade está em período de descanso. Este local físico está fechado.**"
                    )
                return

            self._sleep_notice_channels.discard(message.channel.id)
            if not self.ai_service.enabled:
                return

            characters = await self.store.list_characters()
            present = [
                item
                for item in characters
                if item.actor_kind == ActorKind.AI
                and item.current_location_key == location.location_key
            ]
            # Uma pessoa pode chamar um NPC de outra sala diretamente neste
            # canal. O local persistido é trocado antes de a pessoa responder.
            normalized = message.content.casefold()
            is_phone_call = any(word in normalized for word in ("ligo", "telefone", "ramal", "chamada"))
            called = [item for item in characters if item.actor_kind == ActorKind.AI
                      and re.search(rf"(?<!\w){re.escape(item.display_name.casefold().split()[0])}(?!\w)", normalized)]
            invited = [item for item in characters if item.actor_kind == ActorKind.AI
                       and item not in present
                       and re.match(rf"^\s*{re.escape(item.display_name.casefold().split()[0])}(?!\w)[,!.?\s]", normalized)]
            addressed = [item for item in present
                         if re.search(rf"(?<!\w){re.escape(item.display_name.casefold().split()[0])}(?!\w)", normalized)]
            conversation_key = (message.channel.id, message.author.id)
            previous = self._active_conversations.get(conversation_key)
            continuing = (next((item for item in present if item.character_id == previous[0]), None)
                          if previous and previous[1] > time.monotonic() else None)
            if is_phone_call and called:
                character = min(called, key=lambda item: normalized.find(item.display_name.casefold().split()[0]))
            elif addressed:
                character = addressed[0]
            elif continuing:
                character = continuing
            elif invited:
                character = invited[0]
            elif "recepção" in (location.room or "").casefold() and any(
                item.character_id == "olivia-bennett" for item in present
            ):
                character = next(item for item in present if item.character_id == "olivia-bennett")
            elif len(present) == 1 and message.content.strip():
                character = present[0]
            else:
                character = None
            if character is None:
                return
            try:
                remote_call = is_phone_call and character.current_location_key != location.location_key
                if character.current_location_key != location.location_key and not remote_call:
                    character = replace(character, current_location_key=location.location_key,
                                        activity=f"presente em {location.room}")
                    await self.store.save_character(character)
                memories = await self.store.list_memories(character.character_id, limit=8)
                completed_action = ""
                recipient = None
                if remote_call:
                    for receiver in characters:
                        if receiver.actor_kind != ActorKind.AI or receiver.character_id == character.character_id:
                            continue
                        first_name = re.escape(receiver.display_name.casefold().split()[0])
                        if re.search(rf"\b(?:diga|avise|mande\s+(?:uma\s+)?mensagem)\s+(?:ao|a|para\s+o)\s+{first_name}\b", normalized):
                            await self.store.add_memory(
                                receiver.character_id,
                                f"Recado de {message.author.display_name} transmitido por {character.display_name}: {message.content}",
                                source_character_id=character.character_id,
                                location_key=character.current_location_key,
                                importance=2,
                            )
                            completed_action = f"Recado para {receiver.display_name} registrado e entregue à memória dele; presença e horário de chegada ainda não confirmados"
                            recipient = receiver
                            break
                if recipient:
                    reply = (f"Anotei seu recado no tablet e encaminhei para {recipient.display_name}, "
                             f"{message.author.display_name}. Ainda não sei quando essa pessoa poderá ir até a sua sala.")
                else:
                    reply = await self.ai_service.reply(
                    character=character,
                    location=(next((place for place in self.location_by_channel.values()
                                    if place.location_key == character.current_location_key), location)
                              if remote_call else location),
                    world=state,
                    human_name=message.author.display_name,
                    human_message=(f"Você está atendendo pelo telefone, sem estar fisicamente nesta sala. {message.content}"
                                   if remote_call else message.content),
                    recent_memory=memories,
                    completed_action=completed_action,
                    )
                payload = self.webhook_service.build_payload(character, location, reply)
                await self.webhook_service.send(message.channel, payload)
                if recipient and re.search(r"\b(?:venha|vir|venha\s+até|passe)\b", normalized) and re.search(
                    r"\b(?:minha\s+sala|sala\s+da\s+céline|sala\s+da\s+celine)\b", normalized
                ):
                    asyncio.create_task(bot._deliver_visit(recipient.character_id, location,
                                                           message.author.display_name))
                self._active_conversations[conversation_key] = (character.character_id, time.monotonic() + 600)
                await self.store.add_memory(
                    character.character_id,
                    f"{message.author.display_name} disse: {message.content}",
                    source_character_id=f"discord:{message.author.id}",
                    location_key=location.location_key,
                    importance=1,
                )
            except Exception as exc:
                logger.exception("Falha na reação de %s: %s", character.character_id, exc)

    bot = ValliereBot()

    def admin_allowed(interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(
            interaction.user.id in settings.authorized_human_ids
            or (permissions and (permissions.administrator or permissions.manage_guild))
        )

    async def guard(interaction) -> bool:
        if interaction.guild_id != settings.discord_guild_id:
            await interaction.response.send_message(
                "Este comando pertence ao servidor VALLIÈRE.", ephemeral=True
            )
            return False
        if not admin_allowed(interaction):
            await interaction.response.send_message(
                "Somente Céline, Emma, Briana ou a administração podem controlar o tempo.",
                ephemeral=True,
            )
            return False
        return True

    def status_embed(snapshot):
        state = snapshot.world
        color = 0x790E22 if state.city_status == CityStatus.ACTIVE else 0x25213B
        embed = discord.Embed(title="VALLIÈRE", color=color)
        embed.description = (
            f"**DIA {state.narrative_day} • {state.day_label} • {state.period.value}**\n"
            f"Clima: {state.weather}\nCidade: **{state.city_status.value}**"
        )
        if snapshot.location_statuses:
            embed.add_field(
                name="Locais",
                value="\n".join(f"• **{name}** — {status}" for name, status in snapshot.location_statuses)[:1024],
                inline=False,
            )
        embed.set_footer(text="A localização das pessoas não é revelada pelo /status.")
        return embed

    @bot.tree.command(name="cidadeacorda", description="Retoma VALLIÈRE em uma nova manhã.")
    async def cidadeacorda(interaction):
        if not await guard(interaction):
            return
        try:
            state = await bot.world_service.wake_city()
        except DomainError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        bot._sleep_notice_channels.clear()
        await interaction.response.send_message(
            f"☀️ **VALLIÈRE — {state.day_label}**\n**MANHÃ**\n\n"
            "A cidade desperta para um novo dia. Cafeterias começam a abrir, "
            "carros voltam às avenidas e as rotinas são retomadas.\n\n"
            "**VALLIÈRE está acordada.**"
        )

    @bot.tree.command(name="iniciarnpcs", description="Ativa a rotina autônoma de todos os NPCs.")
    async def iniciarnpcs(interaction):
        if not await guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            characters = await bot.store.list_characters()
            npcs = [person for person in characters if person.actor_kind == ActorKind.AI]
            for person in npcs:
                if person.profile.get("autonomy_enabled") is not True:
                    await bot.store.save_character(replace(
                        person, profile={**person.profile, "autonomy_enabled": True}
                    ))
            world = await bot.world_service.world()
        except Exception:
            logger.exception("Falha ao iniciar NPCs")
            await interaction.followup.send("Não consegui ativar todos os NPCs. Verifique os logs do bot.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Rotina de **{len(npcs)} NPCs** ativada. "
            + ("A cidade está acordada: a primeira decisão será feita agora; depois, uma a cada 5 minutos."
               if world.city_status == CityStatus.ACTIVE
               else "Eles começarão a agir quando a cidade acordar."),
            ephemeral=True,
        )
        if world.city_status == CityStatus.ACTIVE:
            async def begin() -> None:
                try:
                    await bot._run_npc_turn()
                except Exception:
                    logger.exception("Falha no primeiro turno dos NPCs")
            asyncio.create_task(begin())

    @bot.tree.command(name="pararnpcs", description="Pausa a rotina autônoma de todos os NPCs.")
    async def pararnpcs(interaction):
        if not await guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            characters = await bot.store.list_characters()
            for person in characters:
                if person.actor_kind == ActorKind.AI and person.profile.get("autonomy_enabled") is True:
                    await bot.store.save_character(replace(
                        person, profile={**person.profile, "autonomy_enabled": False}
                    ))
        except Exception:
            logger.exception("Falha ao pausar NPCs")
            await interaction.followup.send("Não consegui pausar todos os NPCs. Verifique os logs do bot.", ephemeral=True)
            return
        await interaction.followup.send("⏸️ Rotina autônoma pausada. Você ainda pode conversar com os NPCs.", ephemeral=True)

    @bot.tree.command(name="avancartempo", description="Avança o período híbrido da cidade.")
    async def avancartempo(interaction):
        if not await guard(interaction):
            return
        try:
            state = await bot.world_service.advance_time()
        except DomainError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"🕰️ **VALLIÈRE agora está em {state.period.value}.**"
        )

    @bot.tree.command(name="cidadedorme", description="Salva e pausa narrativamente VALLIÈRE.")
    async def cidadedorme(interaction):
        if not await guard(interaction):
            return
        await interaction.response.defer()
        try:
            await bot.world_service.sleep_city()
        except DomainError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            "🌙 **VALLIÈRE — MADRUGADA**\n\n"
            "As luzes dos estabelecimentos começam a se apagar, o movimento nas ruas "
            "diminui e VALLIÈRE encerra mais um dia.\n\n"
            "**A cidade está dormindo.**"
        )

    @bot.tree.command(name="status", description="Mostra o estado público de VALLIÈRE.")
    async def status(interaction):
        if interaction.guild_id != settings.discord_guild_id:
            await interaction.response.send_message(
                "Este comando pertence ao servidor VALLIÈRE.", ephemeral=True
            )
            return
        snapshot = await bot.world_service.status()
        await interaction.response.send_message(embed=status_embed(snapshot))

    @bot.tree.command(name="clima", description="Altera o clima narrativo de VALLIÈRE.")
    @app_commands.describe(descricao="Ex.: chuva leve")
    async def clima(interaction, descricao: str):
        if not await guard(interaction):
            return
        try:
            state = await bot.world_service.set_weather(descricao)
        except DomainError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(f"🌦️ Clima atualizado: **{state.weather}**")

    @bot.tree.command(name="moveria", description="Move uma pessoa de IA para este local físico.")
    @app_commands.describe(personagem="ID canônico, ex.: olivia-bennett")
    async def moveria(interaction, personagem: str):
        if not await guard(interaction):
            return
        location = bot.location_by_channel.get(interaction.channel_id)
        if location is None or location.kind != ChannelKind.PHYSICAL:
            await interaction.response.send_message(
                "Use este comando no local físico de destino.", ephemeral=True
            )
            return
        characters = {item.character_id: item for item in await bot.store.list_characters()}
        character = characters.get(personagem.strip().casefold())
        if character is None:
            await interaction.response.send_message("Personagem não encontrado.", ephemeral=True)
            return
        if character.actor_kind != ActorKind.AI:
            await interaction.response.send_message(
                "Bloqueado: personagens humanas são controladas apenas pelas jogadoras.",
                ephemeral=True,
            )
            return
        from dataclasses import replace
        await bot.store.save_character(
            replace(
                character,
                current_location_key=location.location_key,
                activity=f"presente em {location.room}",
            )
        )
        await interaction.response.send_message(
            f"**{character.display_name}** agora está em **{location.room}**.",
            ephemeral=True,
        )

    @bot.tree.command(
        name="diagnosticoia",
        description="Testa a resposta de uma pessoa de IA e mostra a etapa que falhou.",
    )
    @app_commands.describe(personagem="ID canônico, ex.: olivia-bennett")
    async def diagnosticoia(interaction, personagem: str):
        if not await guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        stage = "local"
        try:
            location = bot.location_by_channel.get(interaction.channel_id)
            if location is None or location.kind != ChannelKind.PHYSICAL:
                await interaction.followup.send(
                    "Este canal não é um local físico reconhecido. Use o diagnóstico no #recepção.",
                    ephemeral=True,
                )
                return

            stage = "estado da cidade"
            state = await bot.world_service.world()
            if state.city_status != CityStatus.ACTIVE:
                await interaction.followup.send(
                    "A cidade está dormindo. Use /cidadeacorda antes do teste.",
                    ephemeral=True,
                )
                return

            stage = "personagem e localização"
            characters = {item.character_id: item for item in await bot.store.list_characters()}
            character = characters.get(personagem.strip().casefold())
            if character is None:
                await interaction.followup.send("Personagem não encontrado.", ephemeral=True)
                return
            if character.actor_kind != ActorKind.AI:
                await interaction.followup.send(
                    "Personagens humanas não podem ser testadas pela IA.", ephemeral=True
                )
                return
            if character.current_location_key != location.location_key:
                await interaction.followup.send(
                    f"**{character.display_name}** não está neste local. Use /moveria aqui primeiro.",
                    ephemeral=True,
                )
                return
            if not bot.ai_service.enabled:
                await interaction.followup.send(
                    f"{bot.ai_service.provider_name} não está configurada na hospedagem "
                    f"({bot.ai_service.key_name} ausente).",
                    ephemeral=True,
                )
                return

            stage = "leitura da memória"
            memories = await bot.store.list_memories(character.character_id, limit=8)
            stage = f"resposta da {bot.ai_service.provider_name}"
            reply = await bot.ai_service.reply(
                character=character,
                location=location,
                world=state,
                human_name=interaction.user.display_name,
                human_message=f"{character.display_name}, bom dia! Como estão as coisas por aqui hoje?",
                recent_memory=memories,
            )
            stage = "envio pelo webhook"
            payload = bot.webhook_service.build_payload(character, location, reply)
            await bot.webhook_service.send(interaction.channel, payload)
            await interaction.followup.send(
                f"✅ **{character.display_name} respondeu no canal.** "
                f"Local, cidade, memória, {bot.ai_service.provider_name} e webhook funcionaram. "
                "Agora teste chamando a personagem em uma mensagem comum.",
                ephemeral=True,
            )
        except Exception as exc:
            logger.exception("Diagnóstico de IA falhou na etapa %s: %s", stage, exc)
            # Mostrar apenas código estruturado da API, nunca sua resposta bruta.
            detail = ""
            if isinstance(exc, AIError) and exc.status_code:
                detail = f" (HTTP {exc.status_code})"
                if exc.error_code:
                    detail += f" — código: `{exc.error_code}`"
                if exc.response_kind:
                    detail += f" — formato: {exc.response_kind}"
            await interaction.followup.send(
                f"❌ Falha na etapa **{stage}**{detail}. "
                "Nenhuma chave ou informação interna foi exibida.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="testarwebhook",
        description="Testa a identidade visual de uma pessoa de IA neste local.",
    )
    @app_commands.describe(personagem="ID canônico, ex.: olivia-bennett")
    async def testarwebhook(interaction, personagem: str):
        if not await guard(interaction):
            return
        location = bot.location_by_channel.get(interaction.channel_id)
        if location is None or location.kind != ChannelKind.PHYSICAL:
            await interaction.response.send_message(
                "Use este teste em um canal físico.", ephemeral=True
            )
            return
        characters = {item.character_id: item for item in await bot.store.list_characters()}
        character = characters.get(personagem.strip().casefold())
        if character is None:
            await interaction.response.send_message("Personagem não encontrado.", ephemeral=True)
            return
        if character.actor_kind != ActorKind.AI:
            await interaction.response.send_message(
                "Bloqueado: o sistema jamais fala por uma personagem humana.", ephemeral=True
            )
            return
        payload = bot.webhook_service.build_payload(
            character,
            location,
            "*A identidade deste personagem foi conectada com sucesso.*",
        )
        await interaction.response.defer(ephemeral=True)
        try:
            await bot.webhook_service.send(interaction.channel, payload)
        except discord.Forbidden:
            await interaction.followup.send(
                "O bot precisa da permissão **Gerenciar Webhooks** neste canal.", ephemeral=True
            )
            return
        await interaction.followup.send("Webhook testado com sucesso.", ephemeral=True)

    return bot


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        from dotenv import load_dotenv

        load_dotenv()
        settings = Settings.from_env()
        bot = create_bot(settings)
        bot.run(settings.discord_token, log_handler=None)
    except (ConfigurationError, RuntimeError) as exc:
        raise SystemExit(f"Configuração inválida: {exc}") from exc
