"""Reconnaissance d'un collectif déposé à la place d'un auteur : collaboration, consortium, groupe d'étude, organisme… Sert aux sources qui ne distinguent pas un collectif d'une personne."""

import re

from domain.normalize import normalize_text

_COLLECTIVE_WORDS: frozenset[str] = frozenset(
    {
        "agence",
        "agency",
        "alliance",
        "association",
        "center",
        "centre",
        "cirad",
        "cnrs",
        "cohort",
        "collaborat",  # abréviation WoS
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
        "expedition",
        "federation",
        "fondation",
        "foundation",
        "group",
        "groupe",
        "groups",
        "grp",  # abréviation WoS
        "inrae",
        "initiative",
        "inserm",
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
        "networks",
        "oecd",
        "office",
        "organisation",
        "organization",
        "participants",
        "project",
        "redaktion",
        "registry",
        "reseau",
        "scientists",
        "societe",
        "society",
        "study",
        "team",
        "universidad",
        "universidade",
        "universita",
        "universitat",
        "universite",
        "universiteit",
        "universitet",
        "university",
    }
)

_COLLECTIVE_PHRASES: tuple[str, ...] = (
    "on behalf of",
    "for the",
    "task force",
    "advisory board",
    "panel on",
)
"""Locutions de collectif. « board » et « panel » seuls sont aussi des noms de famille."""

_COLLECTIVE_NAMES: frozenset[str] = frozenset({"et al"})
"""Noms qui désignent un collectif seulement quand ils forment le nom entier."""

_NETWORK_SUFFIX = re.compile(r"[a-z]Net\b")
"""Mot à capitale interne terminé par « Net » : nom de réseau (« MacaqueNet », « WellBeNet »). Le motif tient à la casse du nom brut."""


def is_collective_name(name: str | None) -> bool:
    """Vrai si le nom contient un mot ou une locution de collectif, un nom de réseau (`_NETWORK_SUFFIX`), ou se réduit à « et al ». Hors nom de réseau, la comparaison ignore casse, accents et ponctuation."""
    if name and _NETWORK_SUFFIX.search(name):
        return True
    normalized = normalize_text(name or "")
    if not normalized:
        return False
    if normalized in _COLLECTIVE_NAMES or _COLLECTIVE_WORDS.intersection(normalized.split()):
        return True
    padded = f" {normalized} "
    return any(f" {phrase} " in padded for phrase in _COLLECTIVE_PHRASES)
