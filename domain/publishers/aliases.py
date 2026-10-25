"""Autres noms d'un éditeur : un éditeur que nomment les sources, rapproché du titulaire des préfixes DOI de ses publications.

Deux signaux doivent concorder. Les enregistrements sources qui nomment l'éditeur ont presque tous un DOI Crossref d'un même titulaire de préfixe. Les deux noms sont compatibles : l'un abrège l'autre, l'emboîte ou en est l'acronyme, aux mots génériques près. Une marque ou un éditeur racheté (« BioMed Central » et Springer, « Mary Ann Liebert » et SAGE) partage le titulaire, sans nom compatible : il reste distinct.
"""

from collections.abc import Mapping

from domain.publishers.names import publisher_name_key
from domain.serials.titles import compatible_titles, nested_titles

MIN_RECORDS = 5
"""Nombre minimal d'enregistrements sources à DOI Crossref qui nomment l'éditeur."""

MIN_SHARE = 0.9
"""Part minimale de ces enregistrements qui ont le même titulaire de préfixe."""

# Mots qui désignent l'activité d'éditeur plutôt que l'éditeur : « Karger Publishers » et « S. Karger ».
_GENERIC_WORDS = frozenset(
    {"the", "publishing", "publishers", "publisher", "publ", "pub", "publications", "verlag", "group", "groupe"}
)  # fmt: skip


def prefix_holder(holders: Mapping[int, int]) -> int | None:
    """Titulaire de préfixe qui réunit au moins `MIN_SHARE` des enregistrements sources d'un éditeur, eux-mêmes au moins `MIN_RECORDS`. `holders` : nombre d'enregistrements par titulaire."""
    total = sum(holders.values())
    if total < MIN_RECORDS:
        return None
    holder, count = max(holders.items(), key=lambda item: item[1])
    return holder if count / total >= MIN_SHARE else None


def _forms(name: str) -> set[str]:
    core = " ".join(w for w in publisher_name_key(name).split() if w not in _GENERIC_WORDS)
    return {form for form in (name, core) if form}


def compatible_publisher_names(a: str, b: str) -> bool:
    """Indique si deux noms désignent le même éditeur : égaux, emboîtés ou abrégés l'un dans l'autre (`compatible_titles`), tels quels ou privés des mots génériques et des formes juridiques."""
    return any(
        x.casefold() == y.casefold() or compatible_titles(x, y) or nested_titles(x, y)
        for x in _forms(a)
        for y in _forms(b)
    )
