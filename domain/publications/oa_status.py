"""Statuts open access d'une publication, leur rang et leurs niveaux d'accès."""

from enum import StrEnum


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
    """Statut d'une publication sans signal des sources. Le statut d'un enregistrement source sans signal est `NULL`."""


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
"""Rang des statuts open access, du plus ouvert au moins ouvert. Un statut à licence connue passe avant `bronze`, sans licence : `green` d'abord."""

ACCESS_LEVELS: dict[str, frozenset[str]] = {
    "open": frozenset(
        {OaStatus.DIAMOND, OaStatus.GOLD, OaStatus.HYBRID, OaStatus.BRONZE, OaStatus.GREEN}
    ),
    "embargo": frozenset({OaStatus.EMBARGOED}),
    "closed": frozenset({OaStatus.CLOSED, OaStatus.UNKNOWN}),
}
"""Niveaux d'accès, plus grossiers que les statuts. Chaque statut appartient à un seul niveau."""

OA_OPEN_STATUSES: frozenset[str] = ACCESS_LEVELS["open"]

OA_CLOSED_STATUSES: frozenset[str] = ACCESS_LEVELS["closed"]
"""Statuts sans signal d'open access."""
