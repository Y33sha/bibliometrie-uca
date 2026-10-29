"""Reconnaissance d'un collectif déposé à la place d'un auteur : collaboration, consortium, groupe d'étude, organisme… Sert aux sources qui ne distinguent pas un collectif d'une personne."""

from domain.normalize import normalize_text

COLLECTIVE_WORDS: frozenset[str] = frozenset(
    {
        "agence",
        "agency",
        "alliance",
        "association",
        "center",
        "centre",
        "collaboration",
        "collaborations",
        "collaborative",
        "collaborators",
        "commission",
        "committee",
        "consortium",
        "council",
        "department",
        "departement",
        "dept",
        "ecole",
        "editorial",
        "editors",
        "equipe",
        "federation",
        "fondation",
        "foundation",
        "group",
        "groupe",
        "groups",
        "initiative",
        "institut",
        "institute",
        "investigateurs",
        "investigators",
        "laboratoire",
        "laboratory",
        "members",
        "ministere",
        "ministry",
        "network",
        "office",
        "organisation",
        "organization",
        "redaktion",
        "registry",
        "reseau",
        "societe",
        "society",
        "study",
        "team",
        "universitat",
        "universite",
        "university",
    }
)

COLLECTIVE_PHRASES: tuple[str, ...] = ("on behalf of", "for the", "task force")

# Noms qui désignent un collectif seulement quand ils forment le nom entier.
COLLECTIVE_NAMES: frozenset[str] = frozenset({"et al"})


def is_collective_name(name: str | None) -> bool:
    """Vrai si le nom contient un mot ou une locution de collectif, ou se réduit à « et al ». La comparaison ignore casse, accents et ponctuation."""
    normalized = normalize_text(name or "")
    if not normalized:
        return False
    if normalized in COLLECTIVE_NAMES or COLLECTIVE_WORDS.intersection(normalized.split()):
        return True
    padded = f" {normalized} "
    return any(f" {phrase} " in padded for phrase in COLLECTIVE_PHRASES)
