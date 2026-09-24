from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Literal

from .config import ConfigurationError, Settings

logger = logging.getLogger("valliere")
CLEANUP_CUTOFF = datetime(2026, 9, 24, 15, 55, 12, tzinfo=timezone.utc)
CLEANUP_MARKER = "[VALLIERE-TESTES-LIMPOS-V1]"


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
    from .services.roleplay import split_roleplay
    from .services.visits import may_enter_from_message
    from .services.homes import home_name, may_visit_home, residence_name
    from .services.server_setup import ensure_server_spaces
    from .services.phone import find_contact
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
            self._server_setup_done = False
            self._phone_sessions: dict[tuple[int, int], tuple[str, str, int, float]] = {}
            self._npc_last_exchange: dict[int, float] = {}
            self._home_invites: dict[tuple[str, str], float] = {}
            self._cleanup_task: asyncio.Task | None = None

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
            if not self._server_setup_done:
                try:
                    await ensure_server_spaces(guild, self, self.store, classify_channel)
                except Exception:
                    logger.exception("Não foi possível preparar todos os canais de VALLIÈRE")
                else:
                    self._server_setup_done = True
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
            by_location_key = {place.location_key: place for place in locations}
            for person in await self.store.list_characters():
                if person.actor_kind != ActorKind.AI or not person.residence_location_key:
                    continue
                actual = by_location_key.get(person.current_location_key)
                if actual and not may_visit_home(
                    person.character_id, actual.building,
                    invited_by_resident=self._has_home_invite(
                        person.character_id, actual.building),
                ):
                    await self.store.save_character(replace(
                        person, current_location_key=person.residence_location_key,
                        activity="em casa",
                    ))
            # Personagens recém-criados precisam de um ponto de partida para
            # participar da rotina. Nunca altera uma localização já escolhida.
            public = [place for place in locations if place.kind == ChannelKind.PHYSICAL
                      and place.building in ("NYX Agency & Atelier", "NOIR")]
            for person in await self.store.list_characters():
                if person.actor_kind != ActorKind.AI or person.current_location_key or not public:
                    continue
                profession = str(person.profile.get("profession", "")).casefold()
                if person.residence_location_key and "nyx" not in profession and "noir" not in profession and "bartender" not in profession:
                    await self.store.save_character(replace(
                        person, current_location_key=person.residence_location_key,
                        activity="em casa",
                    ))
                    continue
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
            if self._server_setup_done and (self._cleanup_task is None or self._cleanup_task.done()):
                self._cleanup_task = asyncio.create_task(self._cleanup_old_tests(guild))

        async def _cleanup_old_tests(self, guild) -> None:
            """One-time removal of prelaunch conversations, excluding pinned messages."""
            entrance = next((c for c in guild.text_channels if c.name == "bem-vindos"
                             and c.category and "start" in c.category.name.casefold()), None)
            if entrance is None or CLEANUP_MARKER in (entrance.topic or ""):
                return
            removed = 0
            failures: list[str] = []
            for channel in guild.text_channels:
                location = self.location_by_channel.get(channel.id)
                if location is None or location.kind not in (ChannelKind.PHYSICAL, ChannelKind.DIGITAL):
                    continue
                permissions = channel.permissions_for(guild.me)
                if not (permissions.view_channel and permissions.read_message_history and permissions.manage_messages):
                    failures.append(channel.name)
                    continue
                try:
                    deleted = await channel.purge(
                        limit=None, before=CLEANUP_CUTOFF,
                        check=lambda message: not message.pinned,
                    )
                    removed += len(deleted)
                except Exception:
                    logger.exception("Não consegui limpar os testes em %s", channel.name)
                    failures.append(channel.name)
            if failures:
                logger.warning("Limpeza parcial: %d mensagens; %d canais sem acesso/erro", removed, len(failures))
            else:
                await entrance.edit(topic=f"{entrance.topic or 'Entrada de VALLIÈRE'} {CLEANUP_MARKER}")
                logger.info("Mensagens antigas de teste removidas: %d", removed)

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

        def _has_home_invite(self, character_id: str, building: str | None) -> bool:
            home = residence_name(building)
            return bool(home and self._home_invites.get((home, character_id), 0) > time.monotonic())

        def _record_home_invite(self, owner, spoken: str, characters) -> None:
            words = spoken.casefold()
            if not re.search(r"\b(?:venha|vem|passe|visite|convido)\b", words):
                return
            if not re.search(r"\b(?:minha casa|lá em casa|la em casa|meu apartamento)\b", words):
                return
            for guest in characters:
                if guest.actor_kind != ActorKind.AI or guest.character_id == owner.character_id:
                    continue
                first = re.escape(guest.display_name.casefold().split()[0])
                if re.search(rf"(?<!\w){first}(?!\w)", words):
                    self._home_invites[(home_name(owner.character_id), guest.character_id)] = time.monotonic() + 3600

        async def _npc_exchange(self, speaker, spoken: str, place) -> None:
            """At most one other co-present NPC may answer a natural greeting."""
            now = time.monotonic()
            if now - self._npc_last_exchange.get(place.channel_id, 0) < 600:
                return
            listeners = [npc for npc in await self.store.list_characters()
                         if npc.actor_kind == ActorKind.AI
                         and npc.character_id != speaker.character_id
                         and npc.current_location_key == place.location_key]
            if not listeners:
                return
            addressed = next((npc for npc in listeners if re.search(
                rf"(?<!\w){re.escape(npc.display_name.casefold().split()[0])}(?!\w)",
                spoken.casefold(),
            )), None)
            greeting = re.search(r"\b(?:bom\s+dia|boa\s+tarde|boa\s+noite|olá|ola|oi)\b", spoken.casefold())
            if not addressed and not greeting:
                return
            listener = addressed or random.choice(listeners)
            self._npc_last_exchange[place.channel_id] = now
            world = await self.world_service.world()
            if world.city_status != CityStatus.ACTIVE:
                return
            memories = await self.store.list_memories(listener.character_id, limit=6)
            response = await self.ai_service.reply(
                character=listener, location=place, world=world,
                human_name=speaker.display_name,
                human_message=(f"Outro NPC no mesmo cômodo, {speaker.display_name}, disse: {spoken}. "
                               "Responda somente se você notaria a fala; uma saudação simples "
                               "pede resposta natural e breve, sem inventar amizade ou fatos."),
                recent_memory=memories,
            )
            response = response.strip()
            if not response or response.casefold() in ("não respondo", "fico em silêncio"):
                return
            channel = self.get_channel(place.channel_id)
            if channel:
                await self.webhook_service.send(
                    channel, self.webhook_service.build_payload(listener, place, response),
                )
                await self.store.add_memory(
                    listener.character_id, f"Ouvi {speaker.display_name} dizer: {spoken[:350]}. Respondi: {response[:350]}",
                    source_character_id=speaker.character_id, location_key=place.location_key,
                )
                await self.store.add_memory(
                    speaker.character_id, f"{listener.display_name} respondeu: {response[:400]}",
                    source_character_id=listener.character_id, location_key=place.location_key,
                )

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
            # Escritórios pessoais exigem convite; cada NPC pode voltar para
            # casa, mas não pode escolher a residência de outra pessoa.
            destinations = tuple(place for place in locations
                                 if place.channel_id != current.channel_id
                                 and not (place.room or "").casefold().startswith("sala-")
                                 and may_visit_home(character.character_id, place.building,
                                                    invited_by_resident=self._has_home_invite(
                                                        character.character_id, place.building)))
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
            if action == "speak" and (current.room or "").casefold().startswith("sala-"):
                return
            target = (next(place for place in destinations if place.channel_id == destination_id)
                      if action == "move" else current)
            if action == "move":
                if not may_visit_home(character.character_id, target.building,
                                      invited_by_resident=self._has_home_invite(
                                          character.character_id, target.building)):
                    return
                # Um único current_location_key é gravado antes de falar no destino.
                character = replace(character, current_location_key=target.location_key,
                                    activity=f"presente em {target.room}")
                await self.store.save_character(character)
            if speech:
                self._record_home_invite(character, speech, eligible)
                channel = self.get_channel(target.channel_id)
                payload = self.webhook_service.build_payload(character, target, speech)
                await self.webhook_service.send(channel, payload)
                try:
                    await self._npc_exchange(character, speech, target)
                except Exception:
                    logger.exception("Falha ao conversar entre NPCs em %s", target.room)

        async def _deliver_visit(self, recipient_id: str, destination, caller_name: str,
                                 *, invited_by_resident: bool = False) -> None:
            await asyncio.sleep(12)
            try:
                world = await self.world_service.world()
                if world.city_status != CityStatus.ACTIVE:
                    return
                recipient = next((item for item in await self.store.list_characters()
                                  if item.character_id == recipient_id and item.actor_kind == ActorKind.AI), None)
                channel = self.get_channel(destination.channel_id)
                if recipient is None or channel is None or not may_visit_home(
                    recipient.character_id, destination.building,
                    invited_by_resident=(invited_by_resident or self._has_home_invite(
                        recipient.character_id, destination.building)),
                ):
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

        def _can_invite_home(self, author, building: str | None) -> bool:
            home = residence_name(building)
            if home == "humana-celine":
                return author.id in (settings.celine_user_id, getattr(author.guild, "owner_id", None))
            if home == "humanas-emma-briana":
                return author.id in (settings.emma_user_id, settings.briana_user_id)
            # Um visitante humano não pode convidar terceiros à casa de um NPC.
            return home is None

        async def _remote_exchange(self, channel, author, contact_id: str,
                                   mode: str, spoken: str) -> None:
            _, spoken = split_roleplay(spoken)
            if not spoken.strip():
                return
            world = await self.world_service.world()
            if world.city_status != CityStatus.ACTIVE:
                await channel.send("🌙 A cidade está em descanso; tente novamente quando acordar.")
                return
            characters = await self.store.list_characters()
            contact = next((c for c in characters if c.character_id == contact_id
                            and c.actor_kind == ActorKind.AI), None)
            if contact is None:
                return
            actual_place = next((place for place in self.location_by_channel.values()
                                 if place.location_key == contact.current_location_key), None)
            if actual_place is None:
                # O telefone não fornece um novo local físico nem teleporta a IA.
                from .models import Location
                actual_place = Location(
                    guild_id=channel.guild.id, channel_id=channel.id,
                    category_id=None, category_name="local não informado",
                    channel_name="local não informado", kind=ChannelKind.PHYSICAL,
                    building="local atual não informado", room="local não informado",
                )
            memory = await self.store.list_memories(contact.character_id, limit=8)
            completed = ""
            recipient = None
            if mode == "celular":
                for candidate in characters:
                    if candidate.actor_kind != ActorKind.AI or candidate.character_id == contact_id:
                        continue
                    name = re.escape(candidate.display_name.casefold().split()[0])
                    if re.search(rf"\b(?:diga|avise|mande\s+(?:uma\s+)?mensagem)\s+(?:ao|a|para\s+o)\s+{name}\b", spoken.casefold()):
                        recipient = candidate
                        await self.store.add_memory(
                            candidate.character_id,
                            f"Recado de {author.display_name}, transmitido por telefone por {contact.display_name}: {spoken}",
                            source_character_id=contact.character_id,
                            location_key=contact.current_location_key, importance=2,
                        )
                        completed = f"Recado entregue a {candidate.display_name}; visita ou horário ainda não confirmados"
                        break
            if recipient:
                reply = (f"Anotei o recado e encaminhei a {recipient.display_name}, "
                         f"{author.display_name}. Ainda não confirmei quando poderá aparecer.")
            else:
                reply = await self.ai_service.reply(
                    character=contact, location=actual_place, world=world,
                    human_name=author.display_name,
                    human_message=("Vocês conversam por ligação de celular. " if mode == "celular"
                                   else "Você recebeu uma mensagem de texto no celular. ")
                                  + "Ninguém mudou de local por causa deste contato. "
                                  + f"Mensagem de {author.display_name}: {spoken}",
                    recent_memory=memory, completed_action=completed,
                )
            payload = self.webhook_service.build_phone_payload(contact, reply, mode)
            await self.webhook_service.send(channel, payload)
            await self.store.add_memory(
                contact.character_id,
                f"{mode.capitalize()} de {author.display_name}: {spoken}. Resposta: {reply[:500]}",
                source_character_id=f"discord:{author.id}",
                location_key=contact.current_location_key, importance=1,
            )
            here = self.location_by_channel.get(channel.id)
            if recipient and here and here.building == "NYX Agency & Atelier" and (
                here.room or "").casefold().startswith("sala-") and re.search(
                r"\b(?:venha|vir|passe)\b", spoken.casefold()
            ) and re.search(r"\b(?:minha\s+sala|sala\s+da\s+céline|sala\s+da\s+celine)\b", spoken.casefold()):
                asyncio.create_task(self._deliver_visit(
                    recipient.character_id, here, author.display_name,
                ))

        async def on_message(self, message) -> None:
            if message.author.bot or message.webhook_id or not message.guild:
                return
            session_key = (message.guild.id, message.author.id)
            session = self._phone_sessions.get(session_key)
            if session and session[2] == message.channel.id and session[3] > time.monotonic():
                if not message.content.strip():
                    return
                try:
                    await self._remote_exchange(
                        message.channel, message.author, session[0], session[1], message.content,
                    )
                    self._phone_sessions[session_key] = (
                        session[0], session[1], session[2], time.monotonic() + 600,
                    )
                except Exception:
                    logger.exception("Falha em comunicação por celular com %s", session[0])
                return
            if session and session[3] <= time.monotonic():
                self._phone_sessions.pop(session_key, None)
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
            actions, speech = split_roleplay(message.content)
            normalized = speech.casefold()
            action_text = actions.casefold()
            def name_in_text(person) -> bool:
                names = [person.display_name.casefold().split()[0]]
                if person.character_id == "nathan":
                    names.extend(("natam", "natham"))
                return any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalized) for name in names)
            # Ligações e mensagens remotas agora usam /celular e /mensagem.
            is_phone_call = False
            called = []
            invited = [item for item in characters if item.actor_kind == ActorKind.AI
                       and item not in present
                       and may_enter_from_message(location.building, speech)
                       and (may_visit_home(item.character_id, location.building,
                                           invited_by_resident=self._has_home_invite(
                                               item.character_id, location.building))
                            or self._can_invite_home(message.author, location.building))
                       and re.match(rf"^\s*{re.escape(item.display_name.casefold().split()[0])}(?!\w)[,!.?\s]", normalized)]
            addressed = [item for item in present if name_in_text(item)]
            conversation_key = (message.channel.id, message.author.id)
            previous = self._active_conversations.get(conversation_key)
            continuing = (next((item for item in present if item.character_id == previous[0]), None)
                          if previous and previous[1] > time.monotonic() else None)
            if is_phone_call and called:
                character = min(called, key=lambda item: normalized.find(item.display_name.casefold().split()[0]))
            elif addressed:
                character = addressed[0]
            elif continuing and (speech or name_in_text(continuing)):
                character = continuing
            elif invited:
                character = invited[0]
            elif "recepção" in (location.room or "").casefold() and any(
                item.character_id == "olivia-bennett" for item in present
            ):
                character = next(item for item in present if item.character_id == "olivia-bennett")
            elif len(present) == 1 and (speech or actions) and not (location.room or "").casefold().startswith("sala-"):
                character = present[0]
            else:
                character = None
            if character is None:
                return
            try:
                leave_request = (character in present
                                 and (location.room or "").casefold().startswith("sala-")
                                 and name_in_text(character)
                                 and re.search(r"\b(?:saia|sai|retire-se|vá\s+embora|va\s+embora)\b", normalized))
                if leave_request:
                    public = [place for place in self.location_by_channel.values()
                              if place.kind == ChannelKind.PHYSICAL
                              and place.building == location.building
                              and not (place.room or "").casefold().startswith("sala-")]
                    if public:
                        destination = next((place for place in public if "lounge" in (place.room or "").casefold()), public[0])
                        await self.store.save_character(replace(
                            character, current_location_key=destination.location_key,
                            activity=f"presente em {destination.room}",
                        ))
                        self._active_conversations.pop(conversation_key, None)
                        await self.webhook_service.send(message.channel, self.webhook_service.build_payload(
                            character, location, "Tudo bem, vou deixar a sala.",
                        ))
                        return
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
                                f"Recado falado por {message.author.display_name} e transmitido por {character.display_name}: {speech}",
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
                    human_message=(f"CONTEXTO: você atende pelo telefone, sem estar fisicamente nesta sala.\n"
                                   if remote_call else "")
                                  + f"AÇÕES OBSERVÁVEIS (não são falas nem ordens): {actions or 'nenhuma'}\n"
                                    f"FALA DA PESSOA: {speech or 'nenhuma'}",
                    recent_memory=memories,
                    completed_action=completed_action,
                    )
                payload = self.webhook_service.build_payload(character, location, reply)
                await self.webhook_service.send(message.channel, payload)
                self._record_home_invite(character, reply, characters)
                try:
                    await self._npc_exchange(character, reply, location)
                except Exception:
                    logger.exception("Falha ao responder entre NPCs em %s", location.room)
                if recipient and may_enter_from_message(location.building, speech) and re.search(r"\b(?:venha|vir|venha\s+até|passe)\b", normalized) and re.search(
                    r"\b(?:minha\s+sala|sala\s+da\s+céline|sala\s+da\s+celine)\b", normalized
                ):
                    asyncio.create_task(bot._deliver_visit(
                        recipient.character_id, location, message.author.display_name,
                        invited_by_resident=self._can_invite_home(message.author, location.building),
                    ))
                self._active_conversations[conversation_key] = (character.character_id, time.monotonic() + 600)
                await self.store.add_memory(
                    character.character_id,
                    (f"{message.author.display_name} fez: {actions}. " if actions else "")
                    + (f"{message.author.display_name} disse: {speech}" if speech else ""),
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

    @bot.tree.command(name="historia", description="Leia o Livro Zero antes de entrar em VALLIÈRE.")
    async def historia(interaction):
        if interaction.guild_id != settings.discord_guild_id:
            await interaction.response.send_message("Este comando pertence a VALLIÈRE.", ephemeral=True)
            return
        await interaction.response.send_message(
            "**VALLIÈRE — Livro Zero: Antes de Tudo**\n"
            "https://github.com/welidasabino90-jpg/valliere-bot/blob/main/HISTORIA.md\n\n"
            "A história termina antes da primeira escolha. Céline, Emma e Briana "
            "continuam sob controle das jogadoras.",
            ephemeral=True,
        )

    async def open_phone(interaction, personagem: str, mode: str, first_message: str | None):
        if interaction.guild_id != settings.discord_guild_id:
            await interaction.response.send_message("Este comando pertence a VALLIÈRE.", ephemeral=True)
            return
        place = bot.location_by_channel.get(interaction.channel_id)
        if place is not None and place.kind == ChannelKind.ADMINISTRATIVE:
            await interaction.response.send_message(
                "Use o celular em um canal da cidade ou em VALLIÈRE Online.", ephemeral=True,
            )
            return
        if not bot.ai_service.enabled:
            await interaction.response.send_message("A IA está indisponível agora.", ephemeral=True)
            return
        state = await bot.world_service.world()
        if state.city_status != CityStatus.ACTIVE:
            await interaction.response.send_message("A cidade está dormindo.", ephemeral=True)
            return
        contact = find_contact(await bot.store.list_characters(), personagem)
        if contact is None:
            await interaction.response.send_message(
                "Não encontrei um único NPC com esse nome. Use o nome completo "
                "ou o identificador, por exemplo `camille-moreau`.", ephemeral=True,
            )
            return
        bot._phone_sessions[(interaction.guild_id, interaction.user.id)] = (
            contact.character_id, mode, interaction.channel_id, time.monotonic() + 600,
        )
        label = "Ligação" if mode == "celular" else "Mensagens"
        await interaction.response.send_message(
            f"📱 **{label} com {contact.display_name}.** Escreva normalmente neste "
            "canal; o contato dura 10 minutos sem mensagens. "
            "Sua fala fica visível neste canal. Use `/desligar` para encerrar.",
            ephemeral=True,
        )
        if first_message:
            try:
                await bot._remote_exchange(
                    interaction.channel, interaction.user, contact.character_id,
                    mode, first_message,
                )
            except Exception:
                logger.exception("Falha no primeiro contato remoto com %s", contact.character_id)
                await interaction.followup.send(
                    "Não consegui completar o contato. Você pode tentar escrever novamente neste canal.",
                    ephemeral=True,
                )

    @bot.tree.command(name="celular", description="Liga para um NPC, sem movê-lo de lugar.")
    @app_commands.describe(personagem="Nome completo ou identificador do NPC",
                           fala="O que dizer na primeira fala (opcional)")
    async def celular(interaction, personagem: str, fala: str | None = None):
        await open_phone(interaction, personagem, "celular", fala)

    @bot.tree.command(name="mensagem", description="Envia mensagens de texto a um NPC.")
    @app_commands.describe(personagem="Nome completo ou identificador do NPC",
                           texto="A primeira mensagem (opcional)")
    async def mensagem(interaction, personagem: str, texto: str | None = None):
        await open_phone(interaction, personagem, "mensagem", texto)

    @bot.tree.command(name="desligar", description="Encerra a ligação ou as mensagens no celular.")
    async def desligar(interaction):
        if interaction.guild_id != settings.discord_guild_id:
            await interaction.response.send_message("Este comando pertence a VALLIÈRE.", ephemeral=True)
            return
        bot._phone_sessions.pop((interaction.guild_id, interaction.user.id), None)
        await interaction.response.send_message("📱 Contato encerrado.", ephemeral=True)

    @bot.tree.command(name="limpartestes", description="Mostra ou limpa conversas antigas de teste.")
    @app_commands.describe(modo="Prévia mostra quantas mensagens; apagar faz a limpeza")
    async def limpartestes(interaction, modo: Literal["prévia", "apagar"] = "prévia"):
        if not await guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        counts: list[tuple[str, int]] = []
        failures: list[str] = []
        total = 0
        for channel in interaction.guild.text_channels:
            place = bot.location_by_channel.get(channel.id)
            if place is None or place.kind not in (ChannelKind.PHYSICAL, ChannelKind.DIGITAL):
                continue
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.read_message_history):
                failures.append(channel.name)
                continue
            if modo == "apagar" and not perms.manage_messages:
                failures.append(channel.name)
                continue
            try:
                if modo == "apagar":
                    removed = await channel.purge(
                        limit=None, before=CLEANUP_CUTOFF,
                        check=lambda message: not message.pinned,
                    )
                    count = len(removed)
                else:
                    count = 0
                    async for message in channel.history(limit=None, before=CLEANUP_CUTOFF):
                        if not message.pinned:
                            count += 1
            except Exception:
                logger.exception("Falha na limpeza do canal %s", channel.name)
                failures.append(channel.name)
                continue
            if count:
                counts.append((channel.name, count))
                total += count
        summary = ", ".join(f"#{name}: {count}" for name, count in counts[:12])
        notice = "apagadas" if modo == "apagar" else "encontradas para limpar"
        await interaction.followup.send(
            f"**{total} mensagens antigas {notice}** em {len(counts)} canais. "
            "Somente conversas anteriores a 24/09/2026 15:55 UTC em locais físicos "
            "e digitais; mensagens fixadas e os canais de entrada/história ficam preservados.\n"
            + (f"Canais: {summary}.\n" if summary else "")
            + (f"Sem permissão/erro em {len(failures)} canais: {', '.join(failures[:6])}." if failures else "")
            + (" Use `/limpartestes modo:apagar` para executar." if modo == "prévia" else ""),
            ephemeral=True,
        )

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
        if not may_visit_home(
            character.character_id, location.building,
            invited_by_resident=bot._has_home_invite(character.character_id, location.building)
            or bot._can_invite_home(interaction.user, location.building),
        ):
            await interaction.response.send_message(
                "Essa é a casa de outra pessoa. O morador precisa convidar este NPC primeiro.",
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
