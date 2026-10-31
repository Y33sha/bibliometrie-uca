"""Recherche et création de la monographie d'un enregistrement source et de son éditeur.

Les normaliseurs des sources appellent ces fonctions pour chaque enregistrement source. La revue se rattache dans la phase `publishing` (`attach_serials`).
"""

from collections.abc import Sequence
from typing import NamedTuple

from domain.monographs.matching import choose_monograph
from domain.normalize import normalize_text, to_plain_text
from domain.publications.identifiers import ISBN
from domain.publishers.names import publisher_name_key
from domain.serials.containers import SeriesDescription, VolumeDescription
from pipeline.transformation.publishing.monographs.store import MonographStore
from pipeline.transformation.publishing.publishers.store import PublisherStore


def find_or_create_publisher(
    name: str | None,
    *,
    openalex_id: str | None = None,
    repo: PublisherStore,
) -> int | None:
    """Trouve ou crée un éditeur. Renvoie son id, ou `None` si le nom est vide.

    Recherche par `openalex_id`, puis par la clé de nom (`publisher_name_key`) parmi les formes de nom. Sans correspondance, l'éditeur est créé avec sa forme de nom.
    """
    if not name:
        return None

    # 1. Par openalex_id
    if openalex_id:
        publisher_id = repo.find_publisher_by_openalex_id(openalex_id)
        if publisher_id:
            name_key = publisher_name_key(to_plain_text(name))
            if name_key:
                repo.add_publisher_name_form(publisher_id, name_key)
            return publisher_id

    # 2-3. Par forme de nom, ou création, puis attribution de l'`openalex_id` à l'éditeur trouvé ou créé.
    matched = match_or_create_publisher(name, repo=repo)
    if matched is None:
        return None
    publisher_id, _ = matched
    if openalex_id:
        repo.set_publisher_openalex_id_if_missing(publisher_id, openalex_id)
    return publisher_id


def match_or_create_publisher(name: str, *, repo: PublisherStore) -> tuple[int, bool] | None:
    """Trouve par sa clé de nom, ou crée, l'éditeur désigné par `name`. Renvoie `(id, created)`, ou `None` si le nom est vide une fois normalisé.

    Le nom affiché, le nom normalisé et la clé dérivent tous du nom mis à plat : un nom reçu avec des entités (`Wood &amp; Fire`) retrouve le même éditeur que reçu en clair.
    """
    name = to_plain_text(name)
    name_normalized = normalize_text(name)
    name_key = publisher_name_key(name)
    if not name_normalized or not name_key:
        return None
    return repo.match_or_create_by_name_form(name, name_normalized, name_key)


def _isbns(values: Sequence[str]) -> list[str]:
    """Renvoie les ISBN-13 valides de `values`, dans l'ordre, sans doublon."""
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
    repo: MonographStore,
) -> int | None:
    """Trouve ou crée une monographie. Renvoie son id, ou `None` sans ISBN connu ni titre, ou si plusieurs volumes de ce titre sont candidats.

    Recherche par ISBN, papier ou électronique, puis par titre normalisé. `choose_monograph` choisit parmi les monographies de ce titre, selon l'éditeur et les ISBN. La monographie trouvée reçoit les champs qui lui manquent.
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
    )


class Containers(NamedTuple):
    """Série et monographie d'un enregistrement source."""

    has_series: bool
    """L'enregistrement source décrit une série (`biblio.journal`)."""
    monograph_id: int | None


def find_or_create_containers(
    series: SeriesDescription | None,
    volume: VolumeDescription | None,
    *,
    publisher_id: int | None,
    monographs: MonographStore,
) -> Containers:
    """Trouve ou crée la monographie d'un enregistrement source, d'après sa série et son volume séparés par `determine_container_type`. Le rattachement aux collections de `publishing` relie la monographie à sa collection."""
    if volume is None:
        return Containers(series is not None, None)
    monograph_id = find_or_create_monograph(
        volume.title,
        isbns=volume.isbns,
        eisbns=volume.eisbns,
        proceedings=volume.proceedings,
        year=volume.year,
        publisher_id=publisher_id,
        repo=monographs,
    )
    return Containers(series is not None, monograph_id)
