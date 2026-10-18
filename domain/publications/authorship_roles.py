"""Rôles canoniques des authorships et mappings par source.

Chaque authorship peut avoir un ou plusieurs rôles (text[]). Les normalizers appellent `map_role(source, raw_role)` pour obtenir la liste de rôles canoniques + un flag `is_corresponding`.
"""

from enum import StrEnum

# ═══════════════════════════════════════════════════════════════════
# Enum canonique
# ═══════════════════════════════════════════════════════════════════


class AuthorshipRole(StrEnum):
    """Rôle canonique d'une signature, valeur de `source_authorships.roles`."""

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


# ═══════════════════════════════════════════════════════════════════
# Mappings par source
# ═══════════════════════════════════════════════════════════════════

# HAL : codes MARC relator + extensions HAL
# crp (correspondent) → author + is_corresponding=True
# co_first_author / co_last_author → author (la position est déjà dans author_position)
_HAL_MAP = {
    "aut": ([AuthorshipRole.AUTHOR], False),
    "crp": ([AuthorshipRole.AUTHOR], True),  # auteur correspondant
    "co_first_author": ([AuthorshipRole.AUTHOR], False),
    "co_last_author": ([AuthorshipRole.AUTHOR], False),
    "trl": ([AuthorshipRole.TRANSLATOR], False),
    "edt": ([AuthorshipRole.EDITOR], False),
    "dir": ([AuthorshipRole.EDITOR], False),  # directeur de publication
    "scientific_editor": ([AuthorshipRole.SCIENTIFIC_EDITOR], False),
    "spk": ([AuthorshipRole.SPEAKER], False),
    "presenter": ([AuthorshipRole.SPEAKER], False),
    "ctb": ([AuthorshipRole.CONTRIBUTOR], False),
    "sad": ([AuthorshipRole.CONTRIBUTOR], False),  # conseiller scientifique
    "csc": ([AuthorshipRole.CONTRIBUTOR], False),  # consultant
    "preface_writer": ([AuthorshipRole.CONTRIBUTOR], False),
    "int": ([AuthorshipRole.CONTRIBUTOR], False),  # interviewer
    "interviewee": ([AuthorshipRole.CONTRIBUTOR], False),
    "reporter": ([AuthorshipRole.CONTRIBUTOR], False),
    "enq": ([AuthorshipRole.CONTRIBUTOR], False),  # enquêteur
    "com": ([AuthorshipRole.CONTRIBUTOR], False),  # compilateur
    "ann": ([AuthorshipRole.CONTRIBUTOR], False),  # annotateur
    "cwt": ([AuthorshipRole.CONTRIBUTOR], False),  # commentateur
    "ill": ([AuthorshipRole.CONTRIBUTOR], False),  # illustrateur
    "pht": ([AuthorshipRole.CONTRIBUTOR], False),  # photographe
    "ctg": ([AuthorshipRole.CONTRIBUTOR], False),  # cartographe
    "wam": ([AuthorshipRole.CONTRIBUTOR], False),  # rédacteur accompagnement
    "win": ([AuthorshipRole.CONTRIBUTOR], False),  # rédacteur introduction
    "dis": ([AuthorshipRole.AUTHOR], False),  # dissertant → auteur
    "rsp": ([AuthorshipRole.CONTRIBUTOR], False),  # répondant
    # Rôles techniques/rares → other
    "pro": ([AuthorshipRole.OTHER], False),
    "ard": ([AuthorshipRole.OTHER], False),
    "prd": ([AuthorshipRole.OTHER], False),
    "stm": ([AuthorshipRole.OTHER], False),
    "med": ([AuthorshipRole.OTHER], False),
    "man": ([AuthorshipRole.OTHER], False),
    "sds": ([AuthorshipRole.OTHER], False),
    "compiler": ([AuthorshipRole.OTHER], False),
    "coding": ([AuthorshipRole.OTHER], False),
    "design": ([AuthorshipRole.OTHER], False),
    "testing": ([AuthorshipRole.OTHER], False),
    "architecture": ([AuthorshipRole.OTHER], False),
    "support": ([AuthorshipRole.OTHER], False),
    "maintenance": ([AuthorshipRole.OTHER], False),
    "documentation": ([AuthorshipRole.OTHER], False),
    "debugging": ([AuthorshipRole.OTHER], False),
    "management": ([AuthorshipRole.OTHER], False),
    "project_manager": ([AuthorshipRole.OTHER], False),
    "ctr": ([AuthorshipRole.OTHER], False),
    "dev": ([AuthorshipRole.OTHER], False),
    "first": ([AuthorshipRole.AUTHOR], False),
    "oth": ([AuthorshipRole.OTHER], False),
}

# WoS
_WOS_MAP = {
    "author": ([AuthorshipRole.AUTHOR], False),
    "book_editor": ([AuthorshipRole.EDITOR], False),
    "book": ([AuthorshipRole.AUTHOR], False),  # auteur de livre
    "corp": ([AuthorshipRole.AUTHOR], False),  # auteur collectif
    "anon": ([AuthorshipRole.AUTHOR], False),  # auteur anonyme
}

# ScanR : mix de codes MARC et de rôles thèses (français, sans accents)
_SCANR_MAP = {
    "author": ([AuthorshipRole.AUTHOR], False),
    "directeurthese": ([AuthorshipRole.THESIS_DIRECTOR], False),
    "rapporteur": ([AuthorshipRole.RAPPORTEUR], False),
    "membrejury": ([AuthorshipRole.JURY_MEMBER], False),
    "presidentjury": ([AuthorshipRole.JURY_PRESIDENT], False),
    "scientific_editor": ([AuthorshipRole.SCIENTIFIC_EDITOR], False),
    "co_first_author": ([AuthorshipRole.AUTHOR], False),
    "co_last_author": ([AuthorshipRole.AUTHOR], False),
    "ctb": ([AuthorshipRole.CONTRIBUTOR], False),
    "sad": ([AuthorshipRole.CONTRIBUTOR], False),
    "edt": ([AuthorshipRole.EDITOR], False),
    "spk": ([AuthorshipRole.SPEAKER], False),
    "presenter": ([AuthorshipRole.SPEAKER], False),
    "trl": ([AuthorshipRole.TRANSLATOR], False),
    "csc": ([AuthorshipRole.CONTRIBUTOR], False),
    "preface_writer": ([AuthorshipRole.CONTRIBUTOR], False),
    "interviewee": ([AuthorshipRole.CONTRIBUTOR], False),
    "int": ([AuthorshipRole.CONTRIBUTOR], False),
    "reporter": ([AuthorshipRole.CONTRIBUTOR], False),
    "enq": ([AuthorshipRole.CONTRIBUTOR], False),
    "ill": ([AuthorshipRole.CONTRIBUTOR], False),
    "pht": ([AuthorshipRole.CONTRIBUTOR], False),
    "cwt": ([AuthorshipRole.CONTRIBUTOR], False),
    "dir": ([AuthorshipRole.EDITOR], False),
    "com": ([AuthorshipRole.CONTRIBUTOR], False),
    "ann": ([AuthorshipRole.CONTRIBUTOR], False),
    "wam": ([AuthorshipRole.CONTRIBUTOR], False),
    "management": ([AuthorshipRole.OTHER], False),
    "project_manager": ([AuthorshipRole.OTHER], False),
    "coding": ([AuthorshipRole.OTHER], False),
    "design": ([AuthorshipRole.OTHER], False),
    "testing": ([AuthorshipRole.OTHER], False),
    "med": ([AuthorshipRole.OTHER], False),
    "oth": ([AuthorshipRole.OTHER], False),
}

# theses.fr : les rôles sont structurels (champs séparés dans le JSON)
# Le mapping est direct, pas besoin de table — voir THESES_FIELD_ROLES ci-dessous
THESES_FIELD_ROLES = {
    "auteurs": [AuthorshipRole.AUTHOR],
    "directeurs": [AuthorshipRole.THESIS_DIRECTOR],
    "rapporteurs": [AuthorshipRole.RAPPORTEUR],
    "examinateurs": [AuthorshipRole.JURY_MEMBER],
    "president": [AuthorshipRole.JURY_PRESIDENT],
}

# Rôles thèse qui impliquent l'appartenance au jury
# → pas besoin d'ajouter jury_member si un de ceux-ci est déjà présent
_THESIS_ROLES_IMPLYING_JURY = {
    AuthorshipRole.THESIS_DIRECTOR,
    AuthorshipRole.RAPPORTEUR,
    AuthorshipRole.JURY_PRESIDENT,
}

_SOURCE_MAPS: dict[str, dict[str, tuple[list[AuthorshipRole], bool]]] = {
    "hal": _HAL_MAP,
    "wos": _WOS_MAP,
    "scanr": _SCANR_MAP,
}


# ═══════════════════════════════════════════════════════════════════
# API publique
# ═══════════════════════════════════════════════════════════════════


def map_role(source: str, raw_role: str | None) -> tuple[list[AuthorshipRole], bool]:
    """Mappe un rôle brut d'une source vers le(s) rôle(s) canonique(s).

    Retourne (roles, is_corresponding). Un rôle absent, ou une source sans table, donne `AUTHOR` ; un rôle inconnu de la table de la source donne `OTHER`.
    """
    if not raw_role:
        return [AuthorshipRole.AUTHOR], False

    source_map = _SOURCE_MAPS.get(source)
    if not source_map:
        return [AuthorshipRole.AUTHOR], False

    raw_role = raw_role.strip()
    if raw_role in source_map:
        return source_map[raw_role]

    # Fallback insensible à la casse
    raw_lower = raw_role.lower()
    for key, val in source_map.items():
        if key.lower() == raw_lower:
            return val

    return [AuthorshipRole.OTHER], False


def merge_roles(role_lists: list[list[AuthorshipRole]]) -> list[AuthorshipRole]:
    """Fusionne plusieurs listes de rôles en supprimant les redondances.

    Applique la règle : si un rôle thèse impliquant le jury est présent, `JURY_MEMBER` est superflu.
    """
    all_roles: set[AuthorshipRole] = set()
    for roles in role_lists:
        all_roles.update(roles)

    # Si un rôle thèse spécifique est présent, retirer jury_member
    if all_roles & _THESIS_ROLES_IMPLYING_JURY:
        all_roles.discard(AuthorshipRole.JURY_MEMBER)

    return sorted(all_roles)
