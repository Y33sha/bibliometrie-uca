"""Service Monographies : trouve ou crée le livre ou le volume d'actes qui contient un document."""

from collections.abc import Sequence

from application.ports.pipeline.monographs import MonographFindOrCreateQueries
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

    Recherche par ISBN, papier ou électronique, puis par titre normalisé chez le même éditeur. Un éditeur absent, du document ou de la monographie, ne sépare pas : seuls deux éditeurs différents le font, et la monographie du même éditeur passe avant celle sans éditeur. Deux monographies de même titre qui portent chacune des ISBN sont distinctes : volumes d'un même ouvrage, ou éditions différentes. Un document sans ISBN rejoint la seule monographie de son titre, ou la seule sans ISBN ; entre plusieurs volumes, il reste sans monographie. La monographie trouvée voit ses champs vides complétés. `journal_id` est la collection, quand un ISSN la désigne.
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
    matches = repo.find_monographs_by_title(title_normalized, publisher_id)
    same_publisher = [
        m for m in matches if publisher_id is not None and m.publisher_id == publisher_id
    ]
    matches = same_publisher or matches
    without_isbn = [m for m in matches if not (m.isbn or m.eisbn)]
    if isbn or eisbn:
        candidates = without_isbn[:1]
    elif len(matches) == 1:
        candidates = matches
    elif len(without_isbn) == 1:
        candidates = without_isbn
    elif matches:
        return None
    else:
        candidates = []
    if candidates:
        return enrich(candidates[0].id)
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
