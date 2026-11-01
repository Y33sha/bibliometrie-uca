"""Autres noms d'un éditeur : un éditeur nommé par les sources, rattaché au titulaire des préfixes DOI de ses publications, ou à l'éditeur de même nom réduit.

Pour le titulaire de préfixe, deux signaux doivent concorder. Les enregistrements sources qui nomment l'éditeur ont presque tous un DOI Crossref d'un même titulaire de préfixe. Les deux noms sont compatibles : l'un abrège l'autre, l'emboîte ou en est l'acronyme, aux mots génériques près. Une marque ou un éditeur racheté (« BioMed Central » et Springer, « Mary Ann Liebert » et SAGE) partage le titulaire, sans nom compatible : il reste distinct.

Deux éditeurs de même nom réduit (`core_publisher_name`) sont un même éditeur : « Brepols Publ » et « Brepols Publishers ».
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import NamedTuple

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

# Noms réduits à un mot courant, partagés par des éditeurs distincts : « Academic Publishers » et « Academic Publications ».
VAGUE_CORE_NAMES = frozenset({"academic", "science", "scientific", "international", "research"})


def prefix_holder(holders: Mapping[int, int]) -> int | None:
    """Renvoie le titulaire de préfixe qui réunit au moins `MIN_SHARE` des enregistrements sources d'un éditeur, eux-mêmes au moins `MIN_RECORDS`.

    Args:
        holders: nombre d'enregistrements sources par titulaire.
    """
    total = sum(holders.values())
    if total < MIN_RECORDS:
        return None
    holder, count = max(holders.items(), key=lambda item: item[1])
    return holder if count / total >= MIN_SHARE else None


def core_publisher_name(name: str) -> str:
    """Renvoie le nom réduit d'un éditeur : sa clé de comparaison (`publisher_name_key`) sans les mots génériques."""
    return " ".join(w for w in publisher_name_key(name).split() if w not in _GENERIC_WORDS)


def _forms(name: str) -> set[str]:
    return {form for form in (name, core_publisher_name(name)) if form}


def compatible_publisher_names(a: str, b: str) -> bool:
    """Vrai si deux noms désignent le même éditeur : égaux, emboîtés ou abrégés l'un dans l'autre (`compatible_titles`), tels quels ou privés des mots génériques et des formes juridiques."""
    return any(
        x.casefold() == y.casefold() or compatible_titles(x, y) or nested_titles(x, y)
        for x in _forms(a)
        for y in _forms(b)
    )


class NamedPublisher(NamedTuple):
    """Éditeur, avec ce qui désigne l'éditeur gardé d'un groupe de même nom réduit."""

    id: int
    name: str
    records: int
    """Nombre d'enregistrements sources qui nomment l'éditeur."""
    holds_prefix: bool
    """Vrai pour un titulaire de préfixe DOI."""


def same_name_merges(publishers: Iterable[NamedPublisher]) -> list[tuple[int, int]]:
    """Renvoie les fusions `(éditeur absorbé, éditeur gardé)` des éditeurs de même nom réduit.

    L'éditeur gardé est le seul titulaire de préfixe DOI du groupe, à défaut le plus nommé par les enregistrements sources, à égalité le plus ancien. Un groupe à plusieurs titulaires de préfixe, ou de nom réduit à un mot courant (`VAGUE_CORE_NAMES`), reste en l'état.
    """
    groups: dict[str, list[NamedPublisher]] = defaultdict(list)
    for p in publishers:
        if (core := core_publisher_name(p.name)) and core not in VAGUE_CORE_NAMES:
            groups[core].append(p)
    merges: list[tuple[int, int]] = []
    for group in groups.values():
        holders = [p for p in group if p.holds_prefix]
        if len(group) < 2 or len(holders) > 1:
            continue
        kept = holders[0] if holders else min(group, key=lambda p: (-p.records, p.id))
        merges.extend((p.id, kept.id) for p in sorted(group) if p.id != kept.id)
    return merges
