"""Données bibliographiques d'un enregistrement source (`source_records.biblio`) : numérotation, éditeur et série, tels que la source les donne. La pagination est décomposée en première et dernière page."""

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import NamedTuple

from domain.serials.containers import SeriesDescription
from domain.serials.issns import IssnStatus, IssnSupport, SerialIssn
from domain.serials.serial import OaModel
from domain.types import JsonValue


class BiblioKey(StrEnum):
    """Clé de `biblio`."""

    VOLUME = "volume"
    ISSUE = "issue"
    FIRST_PAGE = "first_page"
    LAST_PAGE = "last_page"
    ARTICLE_NUMBER = "article_number"
    PUBLISHER = "publisher"
    """Nom de l'éditeur."""
    JOURNAL = "journal"
    """Série qui sert au rattachement de l'enregistrement source à sa revue, clés `JournalKey`."""


class JournalKey(StrEnum):
    """Clé de `biblio.journal`."""

    TITLE = "title"
    ISSNS = "issns"
    """Liste d'ISSN, clés `IssnKey`."""
    OPENALEX_ID = "openalex_id"
    OA_MODEL = "oa_model"


class IssnKey(StrEnum):
    """Clé d'un ISSN de `biblio.journal`."""

    ISSN = "issn"
    SUPPORT = "support"
    LINKING = "linking"
    """Vrai pour l'ISSN-L."""
    MALFORMED = "malformed"
    """Vrai pour une valeur gardée telle que reçue, à forme ou clé de contrôle fausse."""


def journal_biblio(series: SeriesDescription) -> dict[str, JsonValue] | None:
    """Construit `biblio.journal` d'après une série, réduit aux valeurs non vides ; `None` sans aucune valeur."""
    issns: list[JsonValue] = [
        {
            key: value
            for key, value in (
                (IssnKey.ISSN, row.issn),
                (IssnKey.SUPPORT, row.support),
                (IssnKey.LINKING, row.linking),
                (IssnKey.MALFORMED, row.status is IssnStatus.MALFORMED),
            )
            if value
        }
        for row in series.issns
    ]
    journal: dict[str, JsonValue] = {
        key: value
        for key, value in (
            (JournalKey.TITLE, series.title),
            (JournalKey.ISSNS, issns),
            (JournalKey.OPENALEX_ID, series.openalex_id),
            (JournalKey.OA_MODEL, series.oa_model),
        )
        if value
    }
    return journal or None


def with_journal(
    biblio: JsonValue, series: SeriesDescription | None
) -> dict[str, JsonValue] | None:
    """Renvoie `biblio` dont la série est remplacée par `series` ; `None` sans aucune valeur."""
    entries = biblio.items() if isinstance(biblio, Mapping) else ()
    result = {key: value for key, value in entries if key != BiblioKey.JOURNAL}
    journal = journal_biblio(series) if series else None
    if journal:
        result[BiblioKey.JOURNAL] = journal
    return result or None


def journal_series(biblio: Mapping[str, object] | None) -> SeriesDescription | None:
    """Renvoie la série décrite par `biblio.journal`, ou `None` sans série."""
    journal = (biblio or {}).get(BiblioKey.JOURNAL)
    if not isinstance(journal, Mapping):
        return None
    rows = journal.get(JournalKey.ISSNS)
    issns = tuple(
        SerialIssn(
            issn=str(row[IssnKey.ISSN]),
            support=IssnSupport(row[IssnKey.SUPPORT]) if row.get(IssnKey.SUPPORT) else None,
            linking=bool(row.get(IssnKey.LINKING)),
            status=IssnStatus.MALFORMED if row.get(IssnKey.MALFORMED) else IssnStatus.ACTIVE,
        )
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, Mapping) and row.get(IssnKey.ISSN)
    )
    title = journal.get(JournalKey.TITLE)
    openalex_id = journal.get(JournalKey.OPENALEX_ID)
    oa_model = journal.get(JournalKey.OA_MODEL)
    return SeriesDescription(
        title=str(title) if title else None,
        issns=issns,
        openalex_id=str(openalex_id) if openalex_id else None,
        oa_model=OaModel(oa_model) if oa_model else None,
    )


# Une page : un mot sans blanc ni tiret qui contient un chiffre (`45`, `e1234`, `S12`), ou un nombre en chiffres romains (`xiv`).
_PAGE = r"([^\s\-–]*\d[^\s\-–]*|[ivxlcdm]+)"
_PAGE_PREFIX = r"(?:pp?\.?\s+|pp?\.)?"
_PAGE_RANGE = re.compile(rf"^{_PAGE_PREFIX}{_PAGE}\s*[-–]+\s*{_PAGE}$", re.IGNORECASE)
_SINGLE_PAGE = re.compile(rf"^{_PAGE_PREFIX}{_PAGE}$", re.IGNORECASE)
_PAGE_COUNT = re.compile(r"^\d+\s*p\.?$")


class PageRange(NamedTuple):
    """Première et dernière page. Les champs ont le nom de leur clé de `biblio`."""

    first_page: str | None = None
    last_page: str | None = None
    """`None` pour une page seule."""


def parse_pages(raw: str | None) -> PageRange:
    """Lit une pagination donnée en texte : intervalle (`45-67`, `pp. 465-470`) ou page seule (`45`, `p. 3`).

    Un nombre de pages (`728 p.`) et une valeur sans page (`np`) donnent une `PageRange` vide.
    """
    text = (raw or "").strip()
    if not text or _PAGE_COUNT.match(text):
        return PageRange()
    if m := _PAGE_RANGE.match(text):
        return PageRange(m.group(1), m.group(2))
    if m := _SINGLE_PAGE.match(text):
        return PageRange(m.group(1))
    return PageRange()


def compact_biblio(
    *,
    volume: str | None = None,
    issue: str | None = None,
    first_page: str | None = None,
    last_page: str | None = None,
    article_number: str | None = None,
    publisher: str | None = None,
) -> dict[str, JsonValue] | None:
    """Construit `biblio` réduit aux valeurs non vides, sans série ; `None` sans aucune valeur. La normalisation y ajoute la série (`with_journal`)."""
    biblio: dict[str, JsonValue] = {
        key: value
        for key, value in (
            (BiblioKey.VOLUME, volume),
            (BiblioKey.ISSUE, issue),
            (BiblioKey.FIRST_PAGE, first_page),
            (BiblioKey.LAST_PAGE, last_page),
            (BiblioKey.ARTICLE_NUMBER, article_number),
            (BiblioKey.PUBLISHER, publisher),
        )
        if value
    }
    return biblio or None
