from __future__ import annotations

import asyncio
import logging

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
    from .services.ai import AIError, GroqService
    from .services.webhooks import WebhookService
    from .services.world import DomainError, WorldService
    from .stores.supabase import SupabaseStore

    class ValliereBot(commands.Bot):
        def __init__(self) -> None:
            intents = discord.Intents.default()
            intents.guilds = True
            intents.messages = True
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
            self.ai_service = GroqService(settings.groq_api_key, settings.groq_model)
            self.location_by_channel: dict[int, object] = {}
            self._sleep_notice_channels: set[int] = set()

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
            if not present:
                return

            # Presença não significa participação: uma mensagem comum não faz
            # todos os presentes responderem. Menção pelo nome dá iniciativa.
            normalized = message.content.casefold()
            addressed = [
                item for item in present
                if item.display_name.casefold().split()[0] in normalized
                or item.display_name.casefold() in normalized
            ]
            if not addressed:
                return

            character = addressed[0]
            memories = await self.store.list_memories(character.character_id, limit=8)
            try:
                reply = await self.ai_service.reply(
                    character=character,
                    location=location,
                    world=state,
                    human_name=message.author.display_name,
                    human_message=message.content,
                    recent_memory=memories,
                )
                payload = self.webhook_service.build_payload(character, location, reply)
                await self.webhook_service.send(message.channel, payload)
                await self.store.add_memory(
                    character.character_id,
                    f"{message.author.display_name} disse: {message.content}",
                    source_character_id=f"discord:{message.author.id}",
                    location_key=location.location_key,
                    importance=1,
                )
            except (AIError, Exception) as exc:
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
