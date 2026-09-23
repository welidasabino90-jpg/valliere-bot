from __future__ import annotations

from .models import ActorKind, Character


def initial_characters(
    celine_user_id: int | None = None,
    emma_user_id: int | None = None,
    briana_user_id: int | None = None,
) -> tuple[Character, ...]:
    """Elenco canônico inicial. Perfis profundos entram na Fase 2."""

    humans = (
        Character("celine", "Céline", ActorKind.HUMAN, celine_user_id),
        Character("emma", "Emma", ActorKind.HUMAN, emma_user_id),
        Character("briana", "Briana", ActorKind.HUMAN, briana_user_id),
    )
    ai_data = (
        ("helena-laurent", "Helena Laurent", "arquiteta e designer de interiores"),
        ("arthur-laurent", "Arthur Laurent", "advogado empresarial"),
        ("liam-laurent", "Liam Laurent", "empresário de eventos e entretenimento"),
        ("amelie-laurent", "Amélie Laurent", "universitária"),
        ("vivienne", "Vivienne", "vida social própria"),
        ("charles", "Charles", "empresário"),
        ("camille", "Camille", "universitária"),
        ("nathan", "Nathan", "profissão a definir em jogo"),
        ("olivia-bennett", "Olivia Bennett", "assistente executiva de Céline"),
        ("noah-carter", "Noah Carter", "diretor de casting"),
        ("camille-moreau", "Camille Moreau", "relações públicas"),
        ("theo-beaumont", "Theo Beaumont", "produtor de moda"),
        ("gabriel-torres", "Gabriel Torres", "segurança da NYX"),
        ("matteo-ricci", "Matteo Ricci", "proprietário do NOIR"),
        ("sofia-bellini", "Sofia Bellini", "bartender"),
        ("luca-moretti", "Luca Moretti", "profissão canônica registrada"),
        ("kiara-bennett", "Kiara Bennett", "profissão canônica registrada"),
        ("maya-collins", "Maya Collins", "profissão canônica registrada"),
        ("ryan-blake", "Ryan Blake", "profissão canônica registrada"),
    )
    ais = tuple(
        Character(slug, name, ActorKind.AI, profile={"profession": profession})
        for slug, name, profession in ai_data
    )
    return humans + ais

