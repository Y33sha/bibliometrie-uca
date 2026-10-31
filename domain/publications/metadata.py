"""Règles sur les métadonnées d'une publication : statut open access, titre, métadonnées minimales."""

import re
from enum import StrEnum

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
