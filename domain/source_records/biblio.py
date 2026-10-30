"""Données bibliographiques d'un enregistrement source (`source_records.biblio`) : numérotation, éditeur et revue, tels que la source les donne. La pagination est décomposée en première et dernière page."""

import re
from enum import StrEnum
from typing import NamedTuple

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
    """Revue, clés `JournalKey`."""


class JournalKey(StrEnum):
    """Clé de `biblio.journal`."""

    TITLE = "title"
    ISSN = "issn"
    EISSN = "eissn"
    ISSNL = "issnl"
    OPENALEX_ID = "openalex_id"


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
    journal_title: str | None = None,
    journal_issn: str | None = None,
    journal_eissn: str | None = None,
    journal_issnl: str | None = None,
    journal_openalex_id: str | None = None,
) -> dict[str, JsonValue] | None:
    """Construit `biblio` réduit aux valeurs non vides ; `None` sans aucune valeur."""
    journal: dict[str, JsonValue] = {
        key: value
        for key, value in (
            (JournalKey.TITLE, journal_title),
            (JournalKey.ISSN, journal_issn),
            (JournalKey.EISSN, journal_eissn),
            (JournalKey.ISSNL, journal_issnl),
            (JournalKey.OPENALEX_ID, journal_openalex_id),
        )
        if value
    }
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
    if journal:
        biblio[BiblioKey.JOURNAL] = journal
    return biblio or None
