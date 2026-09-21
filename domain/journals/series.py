"""Niveau d'un titre de conteneur : série (revue, collection, série d'actes) ou volume (livre, volume d'actes).

Un titre qui désigne une édition ou un tome précis est celui d'un volume : une année (« NuFACT 2022 »), un ordinal d'édition (« 8th International Conference », « 34es Journées »), un numéro de volume (« LIPIcs, Volume 364 »). Un titre sans aucune de ces marques est celui d'une série. Le titre de série d'un titre de volume retire ces marques ; sa forme normalisée, la clé de série, est commune aux volumes d'une même série.
"""

import re
from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum
from typing import NamedTuple

from domain.journals.journal import JournalType
from domain.journals.titles import names_a_dated_event
from domain.normalize import normalize_text

# Ordinal d'édition, anglais (« 8th », « 21st »), français (« 34es », « 6èmes », « 1re »), allemand (« 74. Jahrestagung »).
# Un siècle n'est pas une édition : « 19th-century », « XVIe siècle ».
_ORDINAL = re.compile(
    r"\b\d{1,3}(?:st|nd|rd|th|e|es|è|ème|èmes|eme|emes|er|re|ère)\b(?![\s-]*(?:centur|siècle|siecle))"
    r"|\b\d{1,3}\.\s+(?=[A-Za-zÀ-ÿ])",
    re.IGNORECASE,
)
# Numéro de volume ou de tome : « Volume 364 », « Vol. 3 », « Tome 2 », « Band 12 ».
_VOLUME_NUMBER = re.compile(r"\b(?:vol(?:ume)?|tome|band|bd)\.?\s*\d+\b", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(?:1[89]\d\d|20\d\d)(?!\d)")
# Date d'une édition : « September 7 - 12 », « 16 juin », « 6-8 mars ».
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre"
    "|décembre|decembre"
)
_DATE = re.compile(
    rf"\b(?:(?:{_MONTHS})\s+\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?"
    rf"|\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?\s+(?:{_MONTHS}))\b",
    re.IGNORECASE,
)
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,;.)\]])")
_REPEATED_SEPARATORS = re.compile(r"([,;])(?:\s*[,;])+")
_SPACES = re.compile(r"\s+")
# Reste d'une marque retirée : trait d'union détaché (« VTC2022-Spring »), préposition finale (« … du 6 juin 2019 »).
_DETACHED_HYPHEN = re.compile(r"\s+([-–])(?=\w)")
_TRAILING_PREPOSITION = re.compile(
    r"\s+(?:du|de|des|le|la|les|en|au|aux|à|of|the|in|on|at)$", re.IGNORECASE
)


_SERIES_OF_VOLUMES = frozenset({JournalType.PROCEEDINGS, JournalType.BOOK_SERIES})


def holds_volumes(journal_type: JournalType) -> bool:
    """Indique si une entrée de `journals` de ce type réunit des volumes : série d'actes ou collection de livres. Une revue peut porter une année dans son titre (« Periodontology 2000 »)."""
    return journal_type in _SERIES_OF_VOLUMES


class ContainerLevel(StrEnum):
    """Niveau d'un conteneur."""

    SERIES = "series"
    VOLUME = "volume"


def container_level(title: str) -> ContainerLevel:
    """Niveau d'un titre de conteneur, d'après ses marques d'édition ou de tome."""
    if names_a_dated_event(title) or _ORDINAL.search(title) or _VOLUME_NUMBER.search(title):
        return ContainerLevel.VOLUME
    return ContainerLevel.SERIES


def series_title(title: str) -> str:
    """Titre de la série d'un titre de volume : le titre sans dates, années, ordinaux d'édition ni numéros de volume, casse et ponctuation conservées.

    « Proceedings of the 12th International Conference on Operations Research and Enterprise Systems (ICORES 2023) » donne « Proceedings of the International Conference on Operations Research and Enterprise Systems (ICORES) ».
    """
    for pattern in (_DATE, _VOLUME_NUMBER, _ORDINAL, _YEAR):
        title = pattern.sub(" ", title)
    title = _EMPTY_BRACKETS.sub(" ", title)
    title = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", title)
    title = _REPEATED_SEPARATORS.sub(r"\1", title)
    title = _DETACHED_HYPHEN.sub(r"\1", title)
    title = _SPACES.sub(" ", title).strip(" ,;:–-")
    return _TRAILING_PREPOSITION.sub("", title).strip(" ,;:–-")


def reference_series_title(title: str, sudoc_title: str | None) -> str | None:
    """Titre de référence d'une série à ISSN dont le titre en base a la forme d'un volume, ou `None` pour garder ce titre.

    Le titre de la notice Sudoc fait référence, s'il a lui-même la forme d'une série. À défaut, le titre de série du titre en base (`series_title`).
    """
    if container_level(title) is ContainerLevel.SERIES:
        return None
    for candidate in (sudoc_title, series_title(title)):
        if candidate and container_level(candidate) is ContainerLevel.SERIES:
            return candidate
    return None


def series_key(title: str) -> str:
    """Clé de série d'un titre : son titre de série, normalisé. « NuFACT 2022 » et « NuFACT 2023 » partagent la clé « nufact »."""
    return normalize_text(series_title(title))


class VolumeTitle(NamedTuple):
    """Un volume candidat à une série : son identifiant, son titre et son éditeur."""

    id: int
    title: str
    publisher_id: int | None


class SeriesGroup(NamedTuple):
    """Volumes d'une même série, avec le titre de la série et son éditeur."""

    title: str
    publisher_id: int | None
    volume_ids: tuple[int, ...]


def group_series(volumes: Sequence[VolumeTitle]) -> list[SeriesGroup]:
    """Séries reconnues entre plusieurs volumes : titres de volume (`container_level`) de même clé de série, chez le même éditeur.

    Des titres sans marque d'édition identiques désignent un ouvrage en plusieurs volumes, pas une série. Le titre de la série est le titre de série du plus ancien volume.
    """
    groups: dict[tuple[str, int | None], list[VolumeTitle]] = defaultdict(list)
    for volume in volumes:
        if container_level(volume.title) is ContainerLevel.VOLUME and (
            key := series_key(volume.title)
        ):
            groups[(key, volume.publisher_id)].append(volume)
    return [
        SeriesGroup(
            series_title(min(members).title),
            publisher_id,
            tuple(sorted(v.id for v in members)),
        )
        for (_, publisher_id), members in groups.items()
        if len(members) > 1
    ]
