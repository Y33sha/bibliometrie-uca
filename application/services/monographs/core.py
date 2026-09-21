"""Service Monographies : trouve ou crée le livre ou le volume d'actes qui contient un document."""

from collections.abc import Sequence

from application.ports.pipeline.monographs import MonographFindOrCreateQueries
from domain.monographs.matching import choose_monograph
from domain.normalize import normalize_text, to_plain_text
from domain.publications.identifiers import ISBN


def _isbns(values: Sequence[str]) -> list[str]:
    """ISBN-13 valides de `values`, dans l'ordre, sans doublon."""
    found: list[str] = []
    for value in values:
        isbn = ISBN.try_parse(value)
        if isbn is not None and isbn.value not in found:
            found.append(isbn.value)
    return found


def find_or_create_monograph(
    title: str | None,
    *,
    isbns: Sequence[str] = (),
    eisbns: Sequence[str] = (),
    proceedings: bool,
    year: int | None = None,
    publisher_id: int | None = None,
    journal_id: int | None = None,
    repo: MonographFindOrCreateQueries,
) -> int | None:
    """Trouve ou crée une monographie. Retourne son id, ou `None` sans ISBN connu ni titre.

    Recherche par ISBN, papier ou électronique, puis par titre normalisé : `choose_monograph` choisit parmi les monographies de ce titre, selon l'éditeur et les ISBN. La monographie trouvée voit ses champs vides complétés. `journal_id` est la collection, quand un ISSN la désigne.
    """
    paper = _isbns(isbns)
    electronic = [isbn for isbn in _isbns(eisbns) if isbn not in paper]
    isbn = paper[0] if paper else None
    eisbn = electronic[0] if electronic else None

    def enrich(monograph_id: int) -> int:
        repo.enrich_monograph(
            monograph_id,
            proceedings=proceedings,
            year=year,
            isbn=isbn,
            eisbn=eisbn,
            publisher_id=publisher_id,
            journal_id=journal_id,
        )
        return monograph_id

    for value in (*paper, *electronic):
        if (found := repo.find_monograph_by_isbn(value)) is not None:
            return enrich(found)

    title = to_plain_text(title) if title else ""
    title_normalized = normalize_text(title)
    if not title_normalized:
        return None
    choice = choose_monograph(
        repo.find_monographs_by_title(title_normalized),
        publisher_id=publisher_id,
        has_isbn=bool(isbn or eisbn),
    )
    if choice.monograph_id is not None:
        return enrich(choice.monograph_id)
    if not choice.create:
        return None
    return repo.create_monograph(
        title=title,
        title_normalized=title_normalized,
        proceedings=proceedings,
        year=year,
        isbn=isbn,
        eisbn=eisbn,
        publisher_id=publisher_id,
        journal_id=journal_id,
    )
