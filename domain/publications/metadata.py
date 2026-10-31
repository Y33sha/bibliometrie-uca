"""Règles sur les métadonnées d'une publication : statut open access, titre, métadonnées minimales."""

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol

from domain.normalize import clean_source_text, normalize_text


class OaStatus(StrEnum):
    """Statut open access d'une publication. Reflet du type PostgreSQL `oa_type`."""

    DIAMOND = "diamond"
    GOLD = "gold"
    HYBRID = "hybrid"
    BRONZE = "bronze"
    GREEN = "green"
    EMBARGOED = "embargoed"
    CLOSED = "closed"
    UNKNOWN = "unknown"


# Rang des statuts open access, du plus ouvert au moins ouvert. Un statut à licence connue passe avant `bronze`, sans licence : `green` d'abord.
OA_RANK: dict[str, int] = {
    OaStatus.DIAMOND: 8,
    OaStatus.GOLD: 7,
    OaStatus.HYBRID: 6,
    OaStatus.GREEN: 5,
    OaStatus.BRONZE: 4,
    OaStatus.EMBARGOED: 3,
    OaStatus.CLOSED: 2,
    OaStatus.UNKNOWN: 1,
}

# Statuts open access, qui valident le filtre `oa_status` des lectures.
OA_STATUSES: frozenset[str] = frozenset(OA_RANK)

# Statut d'une publication sans signal des sources. Le statut d'un enregistrement source sans signal est `NULL`.
OA_STATUS_UNKNOWN_DEFAULT = OaStatus.UNKNOWN

# Niveaux d'accès, plus grossiers que les statuts. Chaque statut appartient à un seul niveau.
ACCESS_LEVELS: dict[str, frozenset[str]] = {
    "open": frozenset(
        {OaStatus.DIAMOND, OaStatus.GOLD, OaStatus.HYBRID, OaStatus.BRONZE, OaStatus.GREEN}
    ),
    "embargo": frozenset({OaStatus.EMBARGOED}),
    "closed": frozenset({OaStatus.CLOSED, OaStatus.UNKNOWN}),
}

OA_OPEN_STATUSES: frozenset[str] = ACCESS_LEVELS["open"]

# Statuts sans signal d'open access.
OA_CLOSED_STATUSES: frozenset[str] = ACCESS_LEVELS["closed"]

# Sources qui sont des archives ouvertes.
OPEN_ARCHIVE_SOURCES: frozenset[str] = frozenset({"hal"})


class _OaSignalSource(Protocol):
    """Enregistrement source réduit à sa source et à son statut open access."""

    @property
    def source(self) -> str: ...
    @property
    def oa_status(self) -> str | None: ...


def has_open_archive_deposit(sources: Iterable[_OaSignalSource]) -> bool:
    """Vrai si une archive ouverte déclare un dépôt avec fichier (`green`). Le `green` de HAL vient d'un dépôt ou d'un lien arXiv ou PubMed Central (`derive_hal_oa_status`)."""
    return any(s.source in OPEN_ARCHIVE_SOURCES and s.oa_status == OaStatus.GREEN for s in sources)


def best_oa_status(statuses: Iterable[str | None]) -> str | None:
    """Renvoie le statut le plus ouvert selon `OA_RANK`, ou `None`. Les valeurs vides ou inconnues sont ignorées."""
    best: str | None = None
    best_rank = 0
    for s in statuses:
        if not s:
            continue
        r = OA_RANK.get(s, 0)
        if r > best_rank:
            best, best_rank = s, r
    return best


def publication_oa_status(sources: Iterable[_OaSignalSource], unpaywall: str | None) -> str:
    """Renvoie le statut open access d'une publication, à partir de ses sources et du verdict d'Unpaywall sur son DOI.

    Sans verdict, le statut le plus ouvert des sources. Le verdict l'emporte, sauf dans trois cas où le statut des sources tient : diamond face à gold, qu'Unpaywall ne distingue pas ; embargoed face à closed ou unknown ; un dépôt en archive ouverte face à closed ou unknown, Unpaywall ne voyant pas ce fichier sous le DOI.

    Args:
        unpaywall: verdict d'Unpaywall ; `None` pour un DOI non vérifié ou absent d'Unpaywall.
    """
    sources = list(sources)
    from_sources = best_oa_status(s.oa_status for s in sources) or OA_STATUS_UNKNOWN_DEFAULT
    if unpaywall is None:
        return from_sources
    if from_sources == OaStatus.DIAMOND and unpaywall == OaStatus.GOLD:
        return from_sources
    if unpaywall in OA_CLOSED_STATUSES and (
        from_sources == OaStatus.EMBARGOED or has_open_archive_deposit(sources)
    ):
        return from_sources
    return unpaywall


def has_minimal_publication_metadata(title: str | None, publication_year: int | None) -> bool:
    """Vrai si une publication candidate a un titre et une année, condition de sa création. Une année à 0 compte comme absente."""
    return bool(title) and bool(publication_year)


TITLE_NORMALIZED_MAX_LENGTH = 2000


def is_overlong_title(title: str | None) -> bool:
    """Vrai si le titre normalisé dépasse `TITLE_NORMALIZED_MAX_LENGTH` caractères. Un titre aussi long réunit d'autres textes : programme de congrès, résumé, remerciements."""
    return bool(title) and len(normalize_text(title)) > TITLE_NORMALIZED_MAX_LENGTH


# Espaces ASCII seuls : les espaces insécables de la typographie (« pratiques : ») restent.
_ASCII_WHITESPACE_RE = re.compile(r"[ \t\n\r\f\v]+")


def clean_publication_title(title: str | None) -> str | None:
    """Nettoie un titre à son écriture (`clean_source_text`). Les suites d'espaces ASCII se réduisent à un espace, les espaces de bordure sont retirés."""
    if not title:
        return title
    return _ASCII_WHITESPACE_RE.sub(" ", clean_source_text(title)).strip()


def normalized_title(title: str | None) -> str:
    """Renvoie la forme de comparaison d'un titre, valeur de `source_records.title_normalized`."""
    return normalize_text(clean_publication_title(title) or "")
