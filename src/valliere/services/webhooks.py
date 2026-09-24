from __future__ import annotations

from ..models import ActorKind, Character, ChannelKind, Location, WebhookPayload


class WebhookError(RuntimeError):
    pass


class WebhookService:
    WEBHOOK_NAME = "VALLIÈRE — PERSONAGENS"

    @staticmethod
    def build_payload(character: Character, location: Location, content: str) -> WebhookPayload:
        if character.actor_kind != ActorKind.AI:
            raise WebhookError(
                "Personagens humanas jamais podem receber falas ou ações geradas pelo sistema."
            )
        if location.kind != ChannelKind.PHYSICAL:
            raise WebhookError("Webhooks físicos só podem falar em locais físicos.")
        cleaned = content.strip()[:1900]
        if not cleaned:
            raise WebhookError("A mensagem do personagem está vazia.")
        return WebhookPayload(
            character_id=character.character_id,
            username=character.display_name,
            avatar_url=character.avatar_url,
            content=cleaned,
        )

    @staticmethod
    def build_phone_payload(character: Character, content: str, mode: str) -> WebhookPayload:
        if character.actor_kind != ActorKind.AI:
            raise WebhookError("Personagens humanas não podem receber falas geradas pela IA.")
        label = "ligação" if mode == "celular" else "mensagem"
        cleaned = content.strip()[:1800]
        if not cleaned:
            raise WebhookError("A resposta do celular está vazia.")
        return WebhookPayload(
            character_id=character.character_id,
            username=character.display_name,
            avatar_url=character.avatar_url,
            content=f"📱 **{label}** — {cleaned}",
        )

    async def send(self, channel: object, payload: WebhookPayload) -> None:
        """Cria/reutiliza um webhook do local sem persistir o token no banco."""
        webhooks = await channel.webhooks()  # type: ignore[attr-defined]
        webhook = next((item for item in webhooks if item.name == self.WEBHOOK_NAME), None)
        if webhook is None:
            webhook = await channel.create_webhook(  # type: ignore[attr-defined]
                name=self.WEBHOOK_NAME,
                reason="Identidades individuais das pessoas de IA de VALLIÈRE",
            )
        import discord

        kwargs = {
            "content": payload.content,
            "username": payload.username,
            "wait": True,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if payload.avatar_url:
            kwargs["avatar_url"] = payload.avatar_url
        await webhook.send(**kwargs)
