from __future__ import annotations

from .models import ActorKind, Character


def _ai(character_id: str, name: str, profession: str, **profile) -> Character:
    return Character(
        character_id, name, ActorKind.AI,
        profile={"profession": profession, **profile},
    )


def initial_characters(
    celine_user_id: int | None = None,
    emma_user_id: int | None = None,
    briana_user_id: int | None = None,
) -> tuple[Character, ...]:
    """Elenco-base da Fase 2. Relações familiares ainda não aprovadas ficam sem canonização."""

    humans = (
        Character("celine", "Céline", ActorKind.HUMAN, celine_user_id),
        Character("emma", "Emma", ActorKind.HUMAN, emma_user_id),
        Character("briana", "Briana", ActorKind.HUMAN, briana_user_id),
    )

    # Emma e Briana são irmãs. A família compartilhada será canonizada depois,
    # portanto rascunhos familiares antigos não entram silenciosamente aqui.
    ais = (
        _ai("vivienne", "Vivienne", "vida social própria", age=47,
            personality=["perceptiva", "inteligente", "afetuosa", "firme", "irônica"],
            connection="mãe de Céline"),
        _ai("charles", "Charles", "empresário", age=52,
            personality=["racional", "reservado", "protetor", "trabalhador", "teimoso"],
            connection="pai de Céline"),
        _ai("camille", "Camille", "universitária", age=20,
            personality=["espontânea", "ousada", "social", "engraçada", "impulsiva"],
            connection="irmã mais nova de Céline"),
        _ai("nathan", "Nathan", "profissão a definir em jogo", age=26,
            personality=["leal", "relaxado", "sincero", "independente"],
            connection="amigo de infância de Céline; sem romance predefinido"),
        _ai("olivia-bennett", "Olivia Bennett", "assistente executiva de Céline", age=24,
            personality=["organizada", "inteligente", "observadora", "responsável", "discreta", "curiosa"],
            workplace="NYX Agency & Atelier"),
        _ai("noah-carter", "Noah Carter", "diretor de casting", age=28,
            personality=["extrovertido", "confiante", "exigente", "sociável", "competitivo"],
            workplace="NYX Agency & Atelier"),
        _ai("camille-moreau", "Camille Moreau", "relações públicas", age=26,
            personality=["estratégica", "calma", "inteligente", "persuasiva", "observadora"],
            workplace="NYX Agency & Atelier"),
        _ai("theo-beaumont", "Theo Beaumont", "produtor de moda", age=24,
            personality=["criativo", "carinhoso", "dramático", "engraçado", "perfeccionista"],
            workplace="NYX Agency & Atelier"),
        _ai("gabriel-torres", "Gabriel Torres", "segurança da NYX", age=34,
            personality=["calmo", "educado", "protetor", "reservado", "atento"],
            workplace="NYX Agency & Atelier"),
        _ai("matteo-ricci", "Matteo Ricci", "proprietário do NOIR", age=29,
            personality=["charmoso", "calmo", "observador", "sociável", "discreto", "teimoso"],
            workplace="NOIR", romance="nenhum romance predefinido"),
        _ai("sofia-bellini", "Sofia Bellini", "bartender", age=25,
            personality=["divertida", "sarcástica", "independente", "esperta", "boa ouvinte"],
            workplace="NOIR"),
        _ai("luca-moretti", "Luca Moretti", "fotógrafo freelancer", age=27,
            personality=["ambicioso", "curioso", "artístico", "sociável", "imprevisível"]),
        _ai("kiara-bennett", "Kiara Bennett", "influenciadora", age=24,
            personality=["divertida", "social", "espontânea", "impulsiva"]),
        _ai("maya-collins", "Maya Collins", "profissão a definir", age=22,
            personality=["divertida", "espontânea", "social", "aventureira"]),
        _ai("ryan-blake", "Ryan Blake", "profissão a definir", age=24,
            personality=["brincalhão", "calmo", "leal"], romance="nenhum romance predefinido"),
    )
    return humans + ais
