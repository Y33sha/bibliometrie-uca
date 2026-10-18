"""Reconnaissance d'un nom de signature collective : collaboration, consortium, groupe d'étude, réseau, investigateurs…

Sert aux sources qui ne distinguent pas un collectif d'une personne. La règle porte sur le nom normalisé (`normalize_text`) : un mot ou une locution de collectif suffit.
"""

from domain.normalize import normalize_text

COLLECTIVE_WORDS: frozenset[str] = frozenset(
    {
        "alliance",
        "association",
        "collaboration",
        "collaborations",
        "collaborative",
        "collaborators",
        "committee",
        "consortium",
        "equipe",
        "group",
        "groupe",
        "groups",
        "initiative",
        "investigateurs",
        "investigators",
        "members",
        "network",
        "registry",
        "reseau",
        "societe",
        "society",
        "study",
        "team",
    }
)

COLLECTIVE_PHRASES: tuple[str, ...] = ("on behalf of", "for the", "task force")

# Noms qui désignent un collectif seulement quand ils forment le nom entier.
COLLECTIVE_NAMES: frozenset[str] = frozenset({"et al"})


def is_collective_name(name: str | None) -> bool:
    """Vrai quand `name` désigne un collectif : il contient un mot de `COLLECTIVE_WORDS` ou une locution de `COLLECTIVE_PHRASES`, ou il est un nom de `COLLECTIVE_NAMES`."""
    normalized = normalize_text(name or "")
    if not normalized:
        return False
    if normalized in COLLECTIVE_NAMES or COLLECTIVE_WORDS.intersection(normalized.split()):
        return True
    padded = f" {normalized} "
    return any(f" {phrase} " in padded for phrase in COLLECTIVE_PHRASES)
