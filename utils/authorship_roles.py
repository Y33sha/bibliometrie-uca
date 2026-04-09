"""
Rôles canoniques des authorships et mappings par source.

Chaque authorship peut avoir un ou plusieurs rôles (text[]).
Les normalizers appellent map_roles(source, raw_role) pour obtenir
la liste de rôles canoniques + un flag is_corresponding.
"""

# ═══════════════════════════════════════════════════════════════════
# Enum canonique
# ═══════════════════════════════════════════════════════════════════

AUTHORSHIP_ROLES = {
    "author",               # auteur
    "translator",           # traducteur
    "editor",               # directeur de publication / éditeur d'ouvrage
    "scientific_editor",    # éditeur scientifique (revue)
    "speaker",              # conférencier / orateur
    "contributor",          # contributeur (autre contribution identifiée)
    "thesis_director",      # directeur de thèse
    "rapporteur",           # rapporteur de thèse
    "jury_member",          # membre du jury (examinateur, sans rôle spécifique)
    "jury_president",       # président du jury
    "other",                # autre rôle non classifiable
}


# ═══════════════════════════════════════════════════════════════════
# Mappings par source
# ═══════════════════════════════════════════════════════════════════

# HAL : codes MARC relator + extensions HAL
# crp (correspondent) → author + is_corresponding=True
# co_first_author / co_last_author → author (la position est déjà dans author_position)
_HAL_MAP = {
    "aut":               (["author"], False),
    "crp":               (["author"], True),     # auteur correspondant
    "co_first_author":   (["author"], False),
    "co_last_author":    (["author"], False),
    "trl":               (["translator"], False),
    "edt":               (["editor"], False),
    "dir":               (["editor"], False),     # directeur de publication
    "scientific_editor": (["scientific_editor"], False),
    "spk":               (["speaker"], False),
    "presenter":         (["speaker"], False),
    "ctb":               (["contributor"], False),
    "sad":               (["contributor"], False),  # conseiller scientifique
    "csc":               (["contributor"], False),  # consultant
    "preface_writer":    (["contributor"], False),
    "int":               (["contributor"], False),  # interviewer
    "interviewee":       (["contributor"], False),
    "reporter":          (["contributor"], False),
    "enq":               (["contributor"], False),  # enquêteur
    "com":               (["contributor"], False),  # compilateur
    "ann":               (["contributor"], False),  # annotateur
    "cwt":               (["contributor"], False),  # commentateur
    "ill":               (["contributor"], False),  # illustrateur
    "pht":               (["contributor"], False),  # photographe
    "ctg":               (["contributor"], False),  # cartographe
    "wam":               (["contributor"], False),  # rédacteur accompagnement
    "win":               (["contributor"], False),  # rédacteur introduction
    "dis":               (["author"], False),       # dissertant → auteur
    "rsp":               (["contributor"], False),  # répondant
    # Rôles techniques/rares → other
    "pro":               (["other"], False),
    "ard":               (["other"], False),
    "prd":               (["other"], False),
    "stm":               (["other"], False),
    "med":               (["other"], False),
    "man":               (["other"], False),
    "sds":               (["other"], False),
    "compiler":          (["other"], False),
    "coding":            (["other"], False),
    "design":            (["other"], False),
    "testing":           (["other"], False),
    "architecture":      (["other"], False),
    "support":           (["other"], False),
    "maintenance":       (["other"], False),
    "documentation":     (["other"], False),
    "debugging":         (["other"], False),
    "management":        (["other"], False),
    "project_manager":   (["other"], False),
    "ctr":               (["other"], False),
    "dev":               (["other"], False),
    "first":             (["author"], False),
    "oth":               (["other"], False),
}

# WoS
_WOS_MAP = {
    "author":      (["author"], False),
    "book_editor": (["editor"], False),
    "book":        (["author"], False),       # auteur de livre
    "corp":        (["author"], False),       # auteur collectif
    "anon":        (["author"], False),       # auteur anonyme
}

# ScanR : mix de codes MARC et de rôles thèses (français, sans accents)
_SCANR_MAP = {
    "author":            (["author"], False),
    "directeurthese":    (["thesis_director"], False),
    "rapporteur":        (["rapporteur"], False),
    "membrejury":        (["jury_member"], False),
    "presidentjury":     (["jury_president"], False),
    "scientific_editor": (["scientific_editor"], False),
    "co_first_author":   (["author"], False),
    "co_last_author":    (["author"], False),
    "ctb":               (["contributor"], False),
    "sad":               (["contributor"], False),
    "edt":               (["editor"], False),
    "spk":               (["speaker"], False),
    "presenter":         (["speaker"], False),
    "trl":               (["translator"], False),
    "csc":               (["contributor"], False),
    "preface_writer":    (["contributor"], False),
    "interviewee":       (["contributor"], False),
    "int":               (["contributor"], False),
    "reporter":          (["contributor"], False),
    "enq":               (["contributor"], False),
    "ill":               (["contributor"], False),
    "pht":               (["contributor"], False),
    "cwt":               (["contributor"], False),
    "dir":               (["editor"], False),
    "com":               (["contributor"], False),
    "ann":               (["contributor"], False),
    "wam":               (["contributor"], False),
    "management":        (["other"], False),
    "project_manager":   (["other"], False),
    "coding":            (["other"], False),
    "design":            (["other"], False),
    "testing":           (["other"], False),
    "med":               (["other"], False),
    "oth":               (["other"], False),
}

# theses.fr : les rôles sont structurels (champs séparés dans le JSON)
# Le mapping est direct, pas besoin de table — voir THESES_FIELD_ROLES ci-dessous
THESES_FIELD_ROLES = {
    "auteurs":      ["author"],
    "directeurs":   ["thesis_director"],
    "rapporteurs":  ["rapporteur"],
    "examinateurs": ["jury_member"],
    "president":    ["jury_president"],
}

# Rôles thèse qui impliquent l'appartenance au jury
# → pas besoin d'ajouter jury_member si un de ceux-ci est déjà présent
_THESIS_ROLES_IMPLYING_JURY = {"thesis_director", "rapporteur", "jury_president"}

_SOURCE_MAPS = {
    "hal": _HAL_MAP,
    "wos": _WOS_MAP,
    "scanr": _SCANR_MAP,
}


# ═══════════════════════════════════════════════════════════════════
# API publique
# ═══════════════════════════════════════════════════════════════════

def map_role(source: str, raw_role: str | None) -> tuple[list[str], bool]:
    """Mappe un rôle brut d'une source vers le(s) rôle(s) canonique(s).

    Retourne (roles: list[str], is_corresponding: bool).
    Si le rôle brut est inconnu, retourne (["author"], False) par défaut.
    """
    if not raw_role:
        return ["author"], False

    source_map = _SOURCE_MAPS.get(source)
    if not source_map:
        return ["author"], False

    raw_role = raw_role.strip()
    if raw_role in source_map:
        return source_map[raw_role]

    # Fallback insensible à la casse
    raw_lower = raw_role.lower()
    for key, val in source_map.items():
        if key.lower() == raw_lower:
            return val

    return ["other"], False


def merge_roles(role_lists: list[list[str]]) -> list[str]:
    """Fusionne plusieurs listes de rôles en supprimant les redondances.

    Applique la règle : si un rôle thèse impliquant le jury est présent,
    jury_member est superflu.
    """
    all_roles = set()
    for roles in role_lists:
        all_roles.update(roles)

    # Si un rôle thèse spécifique est présent, retirer jury_member
    if all_roles & _THESIS_ROLES_IMPLYING_JURY:
        all_roles.discard("jury_member")

    return sorted(all_roles)
