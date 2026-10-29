"""Règles sur les métadonnées d'une publication : statut open access, titre, métadonnées minimales."""

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol

from domain.normalize import normalize_text


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


# Rang des statuts open access, du moins ouvert au plus ouvert.
OA_RANK: dict[str, int] = {
    OaStatus.DIAMOND: 8,
    OaStatus.GOLD: 7,
    OaStatus.HYBRID: 6,
    OaStatus.BRONZE: 5,
    OaStatus.GREEN: 4,
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
    """Statut le plus ouvert selon `OA_RANK`, ou `None`. Les valeurs vides ou inconnues sont ignorées."""
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
    """Statut OA d'une publication, à partir de ses sources et du verdict d'Unpaywall sur son DOI (`None` : DOI non vérifié ou absent d'Unpaywall).

    Sans verdict, le statut le plus ouvert des sources. Le verdict l'emporte, sauf dans trois cas où le statut des sources tient : diamond face à gold, qu'Unpaywall ne distingue pas ; embargoed face à closed ou unknown ; un dépôt en archive ouverte face à closed ou unknown, Unpaywall ne voyant pas ce fichier sous le DOI.
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


_HTML_ENTITY_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_HTML_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def _decode_html_entities_once(s: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name.startswith("#"):
            try:
                code = int(name[2:], 16) if name[1] in "xX" else int(name[1:])
                return chr(code)
            except ValueError, OverflowError:
                return m.group(0)
        return _HTML_ENTITY_NAMED.get(name, m.group(0))

    return _HTML_ENTITY_RE.sub(repl, s)


def has_minimal_publication_metadata(title: str | None, publication_year: int | None) -> bool:
    """Vrai si une publication candidate a un titre et une année, condition de sa création. Une année à 0 compte comme absente."""
    return bool(title) and bool(publication_year)


_WHITESPACE_RE = re.compile(r"\s+")


def clean_publication_title(title: str | None) -> str | None:
    """Titre pour l'enregistrement et l'affichage : entités HTML décodées jusqu'à stabilité (`&amp;lt;` d'OpenAlex et de ScanR), espacement réduit à un espace simple. Les balises HTML restent. L'affichage ré-échappe un `&` décodé (« Smith & Jones »)."""
    if not title:
        return title
    for _ in range(4):
        decoded = _decode_html_entities_once(title)
        if decoded == title:
            break
        title = decoded
    return _WHITESPACE_RE.sub(" ", title).strip()


def normalized_title(title: str | None) -> str:
    """Forme de comparaison d'un titre, valeur de `source_records.title_normalized`."""
    return normalize_text(clean_publication_title(title) or "")
