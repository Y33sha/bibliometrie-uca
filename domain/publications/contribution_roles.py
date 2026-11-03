"""Rôles des contributions sources, et traduction des rôles bruts de chaque source."""

from collections.abc import Sequence
from enum import StrEnum


class ContributionRole(StrEnum):
    """Rôle d'une contribution source, valeur de `source_contributions.roles`."""

    AUTHOR = "author"
    TRANSLATOR = "translator"
    EDITOR = "editor"
    """Directeur de publication, éditeur d'ouvrage."""
    SCIENTIFIC_EDITOR = "scientific_editor"
    """Éditeur scientifique d'une revue."""
    SPEAKER = "speaker"
    CONTRIBUTOR = "contributor"
    """Autre contribution identifiée."""
    THESIS_DIRECTOR = "thesis_director"
    RAPPORTEUR = "rapporteur"
    """Rapporteur de thèse."""
    JURY_MEMBER = "jury_member"
    """Membre du jury de thèse sans autre rôle : examinateur."""
    JURY_PRESIDENT = "jury_president"
    OTHER = "other"


_AUTHOR = (ContributionRole.AUTHOR,)
_CONTRIBUTOR = (ContributionRole.CONTRIBUTOR,)
_OTHER = (ContributionRole.OTHER,)

# Codes MARC relator et extensions HAL, repris par ScanR. La position d'un co-premier ou co-dernier auteur est dans `author_position`.
_MARC_ROLES: dict[str, tuple[ContributionRole, ...]] = {
    "aut": _AUTHOR,
    "crp": _AUTHOR,  # auteur correspondant
    "co_first_author": _AUTHOR,
    "co_last_author": _AUTHOR,
    "first": _AUTHOR,
    "dis": _AUTHOR,  # dissertant
    "trl": (ContributionRole.TRANSLATOR,),
    "edt": (ContributionRole.EDITOR,),
    "dir": (ContributionRole.EDITOR,),  # directeur de publication
    "scientific_editor": (ContributionRole.SCIENTIFIC_EDITOR,),
    # Orateur, auteur de la communication.
    "spk": (ContributionRole.AUTHOR, ContributionRole.SPEAKER),
    "presenter": (ContributionRole.AUTHOR, ContributionRole.SPEAKER),
    # Contributeur, cité dans la liste d'auteurs.
    "ctb": (ContributionRole.AUTHOR, ContributionRole.CONTRIBUTOR),
    "sad": _CONTRIBUTOR,  # conseiller scientifique
    "csc": _CONTRIBUTOR,  # consultant
    "preface_writer": _CONTRIBUTOR,
    "int": _CONTRIBUTOR,  # interviewer
    "interviewee": _CONTRIBUTOR,
    "reporter": _CONTRIBUTOR,
    "enq": _CONTRIBUTOR,  # enquêteur
    "com": _CONTRIBUTOR,  # compilateur
    "ann": _CONTRIBUTOR,  # annotateur
    "cwt": _CONTRIBUTOR,  # commentateur
    "ill": _CONTRIBUTOR,  # illustrateur
    "pht": _CONTRIBUTOR,  # photographe
    "ctg": _CONTRIBUTOR,  # cartographe
    "wam": _CONTRIBUTOR,  # rédacteur accompagnement
    "win": _CONTRIBUTOR,  # rédacteur introduction
    "rsp": _CONTRIBUTOR,  # répondant
    **dict.fromkeys(
        (
            "pro",
            "ard",
            "prd",
            "stm",
            "med",
            "man",
            "sds",
            "compiler",
            "coding",
            "design",
            "testing",
            "architecture",
            "support",
            "maintenance",
            "documentation",
            "debugging",
            "management",
            "project_manager",
            "ctr",
            "dev",
            "oth",
        ),
        _OTHER,
    ),  # fmt: skip
}

# Code de l'auteur correspondant.
_CORRESPONDING_CODES = frozenset({"crp"})

_WOS_ROLES: dict[str, tuple[ContributionRole, ...]] = {
    "author": _AUTHOR,
    "book_editor": (ContributionRole.EDITOR,),
    "book": _AUTHOR,  # auteur de livre
    "corp": _AUTHOR,  # auteur collectif
    "anon": _AUTHOR,  # auteur anonyme
}

# ScanR : codes MARC, et rôles de thèse en français sans accents.
_SCANR_ROLES: dict[str, tuple[ContributionRole, ...]] = {
    **_MARC_ROLES,
    "author": _AUTHOR,
    "directeurthese": (ContributionRole.THESIS_DIRECTOR,),
    "rapporteur": (ContributionRole.RAPPORTEUR,),
    "membrejury": (ContributionRole.JURY_MEMBER,),
    "presidentjury": (ContributionRole.JURY_PRESIDENT,),
}

# theses.fr donne un champ par rôle.
THESES_FIELD_ROLES: dict[str, tuple[ContributionRole, ...]] = {
    "auteurs": (ContributionRole.AUTHOR,),
    "directeurs": (ContributionRole.THESIS_DIRECTOR,),
    "rapporteurs": (ContributionRole.RAPPORTEUR,),
    "membresJury": (ContributionRole.JURY_MEMBER,),
    "presidentJury": (ContributionRole.JURY_PRESIDENT,),
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
_THESIS_ROLES_IMPLYING_JURY = THESIS_JURY_ROLES - {ContributionRole.JURY_MEMBER}

_SOURCE_ROLES: dict[str, dict[str, tuple[ContributionRole, ...]]] = {
    "hal": _MARC_ROLES,
    "wos": _WOS_ROLES,
    "scanr": _SCANR_ROLES,
}


def map_role(source: str, raw_role: str | None) -> tuple[list[ContributionRole], bool]:
    """Renvoie les rôles d'une contribution source d'après son rôle brut, et si elle est l'auteur correspondant. Un rôle absent, ou une source sans table, donne `AUTHOR`. Un rôle inconnu donne `OTHER`. La casse est ignorée."""
    source_roles = _SOURCE_ROLES.get(source)
    if not raw_role or not source_roles:
        return list(_AUTHOR), False
    code = raw_role.strip().lower()
    return list(source_roles.get(code, _OTHER)), code in _CORRESPONDING_CODES


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
