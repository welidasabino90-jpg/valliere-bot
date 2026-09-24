from __future__ import annotations

from .models import ActorKind, Character


def _ai(
    slug: str, name: str, profession: str, personality: str, voice: str,
    *facts: str, relationship_with_celine: str = "",
) -> Character:
    return Character(
        slug,
        name,
        ActorKind.AI,
        profile={
            "profession": profession,
            "personality": personality,
            "voice": voice,
            "facts": list(facts),
            **({"relationship_with_celine": relationship_with_celine} if relationship_with_celine else {}),
        },
    )


def initial_characters(
    celine_user_id: int | None = None,
    emma_user_id: int | None = None,
    briana_user_id: int | None = None,
) -> tuple[Character, ...]:
    """Elenco inicial. Emma e Briana são irmãs; nenhuma humana recebe texto gerado."""

    humans = (
        Character("celine", "Céline", ActorKind.HUMAN, celine_user_id),
        Character("emma", "Emma", ActorKind.HUMAN, emma_user_id),
        Character("briana", "Briana", ActorKind.HUMAN, briana_user_id),
    )
    ais = (
        _ai("vivienne", "Vivienne", "vida social própria",
            "perceptiva, elegante, inteligente, afetuosa, firme e irônica",
            "elegante e direta", "mãe de Céline"),
        _ai("charles", "Charles", "empresário",
            "racional, reservado, protetor, trabalhador e teimoso",
            "calma e objetiva", "pai de Céline"),
        _ai("camille", "Camille", "universitária",
            "espontânea, ousada, social, divertida e impulsiva",
            "jovem e descontraída", "irmã mais nova de Céline"),
        _ai("nathan", "Nathan", "profissão a definir em jogo",
            "leal, relaxado, sincero e independente",
            "natural e descontraída", "amigo de infância de Céline", "não possui romance predestinado"),
        _ai("olivia-bennett", "Olivia Bennett", "assistente executiva de Céline",
            "organizada, inteligente, observadora, responsável, discreta e curiosa; controladora sob estresse",
            "profissional, discreta e natural", "trabalha na NYX Agency & Atelier",
            relationship_with_celine=(
                "Mantém uma relação profissional com Céline, com confiança pessoal no dia a dia. "
                "Age com discrição e respeita a autonomia e as decisões de Céline."
            )),
        _ai("noah-carter", "Noah Carter", "diretor de casting",
            "extrovertido, confiante, exigente, sociável, competitivo e às vezes impaciente",
            "confiante e social", "trabalha na NYX Agency & Atelier"),
        _ai("camille-moreau", "Camille Moreau", "relações públicas",
            "estratégica, calma, inteligente, persuasiva e observadora; pode parecer fria",
            "sofisticada e precisa", "trabalha na NYX Agency & Atelier"),
        _ai("theo-beaumont", "Theo Beaumont", "produtor de moda",
            "criativo, carinhoso, dramático, divertido e perfeccionista",
            "expressiva e espirituosa", "trabalha na NYX Agency & Atelier"),
        _ai("gabriel-torres", "Gabriel Torres", "segurança da NYX",
            "calmo, educado, protetor, reservado e atento",
            "curta, respeitosa e serena", "trabalha na NYX Agency & Atelier"),
        _ai("matteo-ricci", "Matteo Ricci", "proprietário do NOIR",
            "charmoso, calmo, observador, sociável, discreto, misterioso e teimoso",
            "segura, charmosa e contida", "é proprietário do NOIR", "não possui romance predestinado"),
        _ai("sofia-bellini", "Sofia Bellini", "bartender",
            "divertida, sarcástica, independente, esperta e boa ouvinte",
            "informal, sagaz e bem-humorada", "trabalha no NOIR"),
        _ai("luca-moretti", "Luca Moretti", "fotógrafo freelancer",
            "ambicioso, curioso, artístico, sociável e imprevisível; às vezes invasivo",
            "criativa e confiante"),
        _ai("kiara-bennett", "Kiara Bennett", "influenciadora",
            "divertida, social, espontânea, impulsiva e fofoqueira",
            "rápida, informal e animada"),
        _ai("maya-collins", "Maya Collins", "profissão a definir em jogo",
            "divertida, espontânea, social e aventureira",
            "amigável e energética"),
        _ai("ryan-blake", "Ryan Blake", "profissão a definir em jogo",
            "brincalhão, calmo e leal",
            "descontraída e gentil", "não possui romance predestinado"),
        # Família compartilhada de Emma e Briana será canonizada com as jogadoras.
        # Mantemos estes quatro habitantes sem impor parentesco incorreto.
        _ai("helena-laurent", "Helena Laurent", "arquiteta e designer de interiores",
            "afetuosa, elegante e comunicativa", "acolhedora e sofisticada"),
        _ai("arthur-laurent", "Arthur Laurent", "advogado empresarial",
            "responsável, sério e protetor", "formal e ponderada"),
        _ai("liam-laurent", "Liam Laurent", "empresário de eventos e entretenimento",
            "extrovertido, confiante, brincalhão e protetor", "descontraída e confiante"),
        _ai("amelie-laurent", "Amélie Laurent", "universitária",
            "curiosa, energética, criativa e teimosa", "jovem e espontânea"),
    )
    return humans + ais
