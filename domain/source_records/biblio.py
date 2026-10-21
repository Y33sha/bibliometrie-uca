"""Données bibliographiques d'un enregistrement source (`source_records.biblio`) : numérotation, éditeur et revue, tels que la source les donne."""

from enum import StrEnum

from domain.types import JsonValue


class BiblioKey(StrEnum):
    """Clé de `biblio`."""

    VOLUME = "volume"
    ISSUE = "issue"
    PAGES = "pages"
    """Plage de pages (HAL)."""
    PAGE = "page"
    """Plage de pages (Crossref)."""
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


def compact_biblio(
    *,
    volume: str | None = None,
    issue: str | None = None,
    pages: str | None = None,
    page: str | None = None,
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
    """`biblio` réduit aux valeurs non vides ; `None` sans aucune valeur."""
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
            (BiblioKey.PAGES, pages),
            (BiblioKey.PAGE, page),
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
