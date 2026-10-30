"""Rôles des contributions sources, et traduction des rôles bruts de chaque source."""

from collections.abc import Sequence
from enum import StrEnum


class ContributionRole(StrEnum):
    """Rôle d'une contribution source, valeur de `source_contributions.roles`."""

    AUTHOR = "author"  # auteur
    TRANSLATOR = "translator"  # traducteur
    EDITOR = "editor"  # directeur de publication / éditeur d'ouvrage
    SCIENTIFIC_EDITOR = "scientific_editor"  # éditeur scientifique (revue)
    SPEAKER = "speaker"  # conférencier / orateur
    CONTRIBUTOR = "contributor"  # contributeur (autre contribution identifiée)
    THESIS_DIRECTOR = "thesis_director"  # directeur de thèse
    RAPPORTEUR = "rapporteur"  # rapporteur de thèse
    JURY_MEMBER = "jury_member"  # membre du jury (examinateur, sans rôle spécifique)
    JURY_PRESIDENT = "jury_president"  # président du jury
    OTHER = "other"  # autre rôle non classifiable


# HAL : codes MARC relator et extensions HAL. La position d'un co-premier ou co-dernier auteur est dans `author_position`.
_HAL_MAP = {
    "aut": ([ContributionRole.AUTHOR], False),
    "crp": ([ContributionRole.AUTHOR], True),  # auteur correspondant
    "co_first_author": ([ContributionRole.AUTHOR], False),
    "co_last_author": ([ContributionRole.AUTHOR], False),
    "trl": ([ContributionRole.TRANSLATOR], False),
    "edt": ([ContributionRole.EDITOR], False),
    "dir": ([ContributionRole.EDITOR], False),  # directeur de publication
    "scientific_editor": ([ContributionRole.SCIENTIFIC_EDITOR], False),
    "spk": (
        [ContributionRole.AUTHOR, ContributionRole.SPEAKER],
        False,
    ),  # orateur, auteur de la communication
    "presenter": (
        [ContributionRole.AUTHOR, ContributionRole.SPEAKER],
        False,
    ),  # orateur, auteur de la communication
    "ctb": (
        [ContributionRole.AUTHOR, ContributionRole.CONTRIBUTOR],
        False,
    ),  # contributeur, cité dans la liste d'auteurs
    "sad": ([ContributionRole.CONTRIBUTOR], False),  # conseiller scientifique
    "csc": ([ContributionRole.CONTRIBUTOR], False),  # consultant
    "preface_writer": ([ContributionRole.CONTRIBUTOR], False),
    "int": ([ContributionRole.CONTRIBUTOR], False),  # interviewer
    "interviewee": ([ContributionRole.CONTRIBUTOR], False),
    "reporter": ([ContributionRole.CONTRIBUTOR], False),
    "enq": ([ContributionRole.CONTRIBUTOR], False),  # enquêteur
    "com": ([ContributionRole.CONTRIBUTOR], False),  # compilateur
    "ann": ([ContributionRole.CONTRIBUTOR], False),  # annotateur
    "cwt": ([ContributionRole.CONTRIBUTOR], False),  # commentateur
    "ill": ([ContributionRole.CONTRIBUTOR], False),  # illustrateur
    "pht": ([ContributionRole.CONTRIBUTOR], False),  # photographe
    "ctg": ([ContributionRole.CONTRIBUTOR], False),  # cartographe
    "wam": ([ContributionRole.CONTRIBUTOR], False),  # rédacteur accompagnement
    "win": ([ContributionRole.CONTRIBUTOR], False),  # rédacteur introduction
    "dis": ([ContributionRole.AUTHOR], False),  # dissertant → auteur
    "rsp": ([ContributionRole.CONTRIBUTOR], False),  # répondant
    # Rôles techniques/rares → other
    "pro": ([ContributionRole.OTHER], False),
    "ard": ([ContributionRole.OTHER], False),
    "prd": ([ContributionRole.OTHER], False),
    "stm": ([ContributionRole.OTHER], False),
    "med": ([ContributionRole.OTHER], False),
    "man": ([ContributionRole.OTHER], False),
    "sds": ([ContributionRole.OTHER], False),
    "compiler": ([ContributionRole.OTHER], False),
    "coding": ([ContributionRole.OTHER], False),
    "design": ([ContributionRole.OTHER], False),
    "testing": ([ContributionRole.OTHER], False),
    "architecture": ([ContributionRole.OTHER], False),
    "support": ([ContributionRole.OTHER], False),
    "maintenance": ([ContributionRole.OTHER], False),
    "documentation": ([ContributionRole.OTHER], False),
    "debugging": ([ContributionRole.OTHER], False),
    "management": ([ContributionRole.OTHER], False),
    "project_manager": ([ContributionRole.OTHER], False),
    "ctr": ([ContributionRole.OTHER], False),
    "dev": ([ContributionRole.OTHER], False),
    "first": ([ContributionRole.AUTHOR], False),
    "oth": ([ContributionRole.OTHER], False),
}

# WoS
_WOS_MAP = {
    "author": ([ContributionRole.AUTHOR], False),
    "book_editor": ([ContributionRole.EDITOR], False),
    "book": ([ContributionRole.AUTHOR], False),  # auteur de livre
    "corp": ([ContributionRole.AUTHOR], False),  # auteur collectif
    "anon": ([ContributionRole.AUTHOR], False),  # auteur anonyme
}

# ScanR : mix de codes MARC et de rôles thèses (français, sans accents)
_SCANR_MAP = {
    "author": ([ContributionRole.AUTHOR], False),
    "directeurthese": ([ContributionRole.THESIS_DIRECTOR], False),
    "rapporteur": ([ContributionRole.RAPPORTEUR], False),
    "membrejury": ([ContributionRole.JURY_MEMBER], False),
    "presidentjury": ([ContributionRole.JURY_PRESIDENT], False),
    "scientific_editor": ([ContributionRole.SCIENTIFIC_EDITOR], False),
    "co_first_author": ([ContributionRole.AUTHOR], False),
    "co_last_author": ([ContributionRole.AUTHOR], False),
    "ctb": (
        [ContributionRole.AUTHOR, ContributionRole.CONTRIBUTOR],
        False,
    ),  # contributeur, cité dans la liste d'auteurs
    "sad": ([ContributionRole.CONTRIBUTOR], False),
    "edt": ([ContributionRole.EDITOR], False),
    "spk": (
        [ContributionRole.AUTHOR, ContributionRole.SPEAKER],
        False,
    ),  # orateur, auteur de la communication
    "presenter": (
        [ContributionRole.AUTHOR, ContributionRole.SPEAKER],
        False,
    ),  # orateur, auteur de la communication
    "trl": ([ContributionRole.TRANSLATOR], False),
    "csc": ([ContributionRole.CONTRIBUTOR], False),
    "preface_writer": ([ContributionRole.CONTRIBUTOR], False),
    "interviewee": ([ContributionRole.CONTRIBUTOR], False),
    "int": ([ContributionRole.CONTRIBUTOR], False),
    "reporter": ([ContributionRole.CONTRIBUTOR], False),
    "enq": ([ContributionRole.CONTRIBUTOR], False),
    "ill": ([ContributionRole.CONTRIBUTOR], False),
    "pht": ([ContributionRole.CONTRIBUTOR], False),
    "cwt": ([ContributionRole.CONTRIBUTOR], False),
    "dir": ([ContributionRole.EDITOR], False),
    "com": ([ContributionRole.CONTRIBUTOR], False),
    "ann": ([ContributionRole.CONTRIBUTOR], False),
    "wam": ([ContributionRole.CONTRIBUTOR], False),
    "management": ([ContributionRole.OTHER], False),
    "project_manager": ([ContributionRole.OTHER], False),
    "coding": ([ContributionRole.OTHER], False),
    "design": ([ContributionRole.OTHER], False),
    "testing": ([ContributionRole.OTHER], False),
    "med": ([ContributionRole.OTHER], False),
    "oth": ([ContributionRole.OTHER], False),
}

# theses.fr donne un champ par rôle.
THESES_FIELD_ROLES = {
    "auteurs": [ContributionRole.AUTHOR],
    "directeurs": [ContributionRole.THESIS_DIRECTOR],
    "rapporteurs": [ContributionRole.RAPPORTEUR],
    "membresJury": [ContributionRole.JURY_MEMBER],
    "presidentJury": [ContributionRole.JURY_PRESIDENT],
}

# Rôles de jury de thèse, donnés par theses.fr et ScanR.
THESIS_JURY_ROLES: frozenset[str] = frozenset(
    {
        ContributionRole.THESIS_DIRECTOR,
        ContributionRole.RAPPORTEUR,
        ContributionRole.JURY_MEMBER,
        ContributionRole.JURY_PRESIDENT,
    }
)

# Rôles de thèse qui impliquent l'appartenance au jury, et rendent `JURY_MEMBER` superflu.
_THESIS_ROLES_IMPLYING_JURY = {
    ContributionRole.THESIS_DIRECTOR,
    ContributionRole.RAPPORTEUR,
    ContributionRole.JURY_PRESIDENT,
}

_SOURCE_MAPS: dict[str, dict[str, tuple[list[ContributionRole], bool]]] = {
    "hal": _HAL_MAP,
    "wos": _WOS_MAP,
    "scanr": _SCANR_MAP,
}


def map_role(source: str, raw_role: str | None) -> tuple[list[ContributionRole], bool]:
    """Renvoie les rôles d'une contribution source d'après son rôle brut, et si elle est l'auteur correspondant. Un rôle absent, ou une source sans table, donne `AUTHOR`. Un rôle inconnu donne `OTHER`. La casse est ignorée."""
    if not raw_role:
        return [ContributionRole.AUTHOR], False

    source_map = _SOURCE_MAPS.get(source)
    if not source_map:
        return [ContributionRole.AUTHOR], False

    raw_role = raw_role.strip()
    if raw_role in source_map:
        return source_map[raw_role]

    raw_lower = raw_role.lower()
    for key, val in source_map.items():
        if key.lower() == raw_lower:
            return val

    return [ContributionRole.OTHER], False


def merge_roles(role_lists: list[list[ContributionRole]]) -> list[ContributionRole]:
    """Renvoie l'union de listes de rôles, sans `JURY_MEMBER` si un autre rôle de thèse l'implique."""
    all_roles: set[ContributionRole] = set()
    for roles in role_lists:
        all_roles.update(roles)

    if all_roles & _THESIS_ROLES_IMPLYING_JURY:
        all_roles.discard(ContributionRole.JURY_MEMBER)

    return sorted(all_roles)


def is_individual_author(roles: Sequence[str] | None, collective: bool) -> bool:
    """Vrai si la contribution source compte dans la liste d'auteurs de son enregistrement source : elle a le rôle `AUTHOR` et n'est pas collective."""
    return not collective and ContributionRole.AUTHOR in (roles or ())
