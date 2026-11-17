"""Adresse concaténée : plusieurs affiliations réunies dans un seul texte, chacune suivie des initiales de ses auteurs."""

import re

_ONE_AUTHOR = r"[A-Z]\.(?:-?[A-Z]\.)*"

_AUTHOR_INITIALS = re.compile(rf"\({_ONE_AUTHOR}(?:(?:,\s*|\s+and\s+){_ONE_AUTHOR})*\)")
"""Groupe d'initiales d'auteurs entre parenthèses : « (D.S., P.C.) », « (J.K.L.-I.) », « (A.-S.R. and B.P.) ».

Le séparateur entre deux auteurs est obligatoire : une suite d'initiales n'admet ainsi qu'un seul découpage, ce qui écarte le backtracking exponentiel sur une parenthèse jamais fermée."""

MIN_INITIALS_GROUPS = 2
"""Nombre de groupes d'initiales d'auteurs à partir duquel une adresse est concaténée. Un seul groupe suit une affiliation unique."""


def is_concatenated(raw_text: str) -> bool:
    """Vrai si l'adresse contient au moins `MIN_INITIALS_GROUPS` groupes d'initiales d'auteurs."""
    return len(_AUTHOR_INITIALS.findall(raw_text)) >= MIN_INITIALS_GROUPS
