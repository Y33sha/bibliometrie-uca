"""Règles de rattachement d'un document à son conteneur, revue ou monographie, et de typage d'une revue selon ses documents."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from domain.journals.journal import OaModel
from domain.journals.series import ContainerLevel, container_level, series_title
from domain.journals.titles import names_a_dated_event, names_proceedings
from domain.normalize import normalize_text, to_plain_text
from domain.publications.identifiers import ISSN
from domain.source_publications.doc_types import map_doc_type

_BOOK = "book"
_BOOK_CHAPTER = "book_chapter"
_CONFERENCE_PAPER = "conference_paper"


class ContainerRole(StrEnum):
    """Ce que le conteneur d'un document désigne."""

    JOURNAL = "journal"
    """Le document paraît dans une revue."""
    BOOK = "book"
    """Le document est lui-même un livre : sa monographie porte son titre."""
    PART = "part"
    """Le document est un chapitre ou un article de congrès : sa monographie est le livre ou le volume d'actes qui le contient."""


def _doc_types(raw_doc_type: str | None, source: str) -> set[str]:
    """Valeurs `doc_type` d'un type brut, composite ou non (WoS « Book Chapter; Proceedings Paper »)."""
    return {map_doc_type(part, source) for part in (raw_doc_type or "").split(";")}


def container_role(
    raw_doc_type: str | None, source: str, *, declares_conference: bool = False
) -> ContainerRole:
    """Rôle du conteneur d'un document, d'après son type brut dans la source. Un document qui déclare un congrès (`declares_conference`) est un article de congrès."""
    types = _doc_types(raw_doc_type, source)
    if declares_conference or types & {_BOOK_CHAPTER, _CONFERENCE_PAPER}:
        return ContainerRole.PART
    if _BOOK in types:
        return ContainerRole.BOOK
    return ContainerRole.JOURNAL


def is_book_or_chapter(raw_doc_type: str | None, source: str) -> bool:
    """Indique si un document est un livre ou un chapitre, hors article de congrès."""
    types = _doc_types(raw_doc_type, source)
    return bool(types & {_BOOK, _BOOK_CHAPTER}) and _CONFERENCE_PAPER not in types


def is_conference(
    raw_doc_type: str | None, source: str, *, declares_conference: bool = False
) -> bool:
    """Indique si un document est issu d'un congrès : sa monographie est un volume d'actes."""
    return declares_conference or _CONFERENCE_PAPER in _doc_types(raw_doc_type, source)


def conference_paper_share(records: Iterable[tuple[str, str | None]]) -> tuple[int, int]:
    """Nombre d'articles de congrès et nombre de documents d'une revue.

    `records` : `(source, type brut)` de chaque document. Le type brut évite de compter les documents que la correction a retypés d'après le type de la revue.
    """
    total = conference = 0
    for source, raw_doc_type in records:
        total += 1
        conference += _CONFERENCE_PAPER in _doc_types(raw_doc_type, source)
    return conference, total


def is_dated_event_without_issn(title: str, *, has_issn: bool) -> bool:
    """Indique si une revue sans ISSN porte le titre d'une édition datée de congrès (`names_a_dated_event`). Une revue avec ISSN peut porter une année dans son titre (« Periodontology 2000 »)."""
    return not has_issn and names_a_dated_event(title)


def is_proceedings_title_without_issn(title: str, *, has_issn: bool) -> bool:
    """Indique si une revue sans ISSN porte un titre d'actes (`names_proceedings`)."""
    return not has_issn and names_proceedings(title)


def holds_mostly_conference_papers(records: Iterable[tuple[str, str | None]]) -> bool:
    """Indique si la majorité stricte des documents d'une revue sont des articles de congrès (`conference_paper_share`)."""
    conference, total = conference_paper_share(records)
    return conference * 2 > total


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerDescription:
    """Ce qu'une source dit du conteneur d'un document, tous niveaux mêlés.

    `journal_title` est la revue d'un article. Pour un livre, un chapitre ou un article de congrès, `collection_title` nomme la collection et `book_title` le livre ou le volume d'actes qui contient le document ; un livre porte son propre titre, `document_title`. Les ISSN sont ceux de la revue ou de la collection : la construction garde les valeurs valides, normalisées, et range les autres dans `rejected_issns`.
    """

    source: str
    raw_doc_type: str | None
    declares_conference: bool = False
    document_title: str | None = None
    journal_title: str | None = None
    collection_title: str | None = None
    book_title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    openalex_id: str | None = None
    oa_model: OaModel | None = None
    isbns: tuple[str, ...] = ()
    eisbns: tuple[str, ...] = ()
    year: int | None = None
    rejected_issns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        rejected = list(self.rejected_issns)
        for field in ("issn", "eissn", "issnl"):
            raw = getattr(self, field)
            issn = ISSN.try_parse(raw)
            if raw and issn is None and raw.strip() not in rejected:
                rejected.append(raw.strip())
            object.__setattr__(self, field, str(issn) if issn else None)
        object.__setattr__(self, "rejected_issns", tuple(rejected))

    @property
    def has_issn(self) -> bool:
        return bool(self.issn or self.eissn or self.issnl)


@dataclass(frozen=True, slots=True, kw_only=True)
class SeriesDescription:
    """Une série telle qu'une source la décrit : revue ou collection. Sans titre, elle se retrouve seulement par ses ISSN."""

    title: str | None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    openalex_id: str | None = None
    oa_model: OaModel | None = None
    rejected_issns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class VolumeDescription:
    """Un livre ou un volume d'actes tel qu'une source le décrit. Sans titre, il se retrouve seulement par ses ISBN."""

    title: str | None
    isbns: tuple[str, ...] = ()
    eisbns: tuple[str, ...] = ()
    proceedings: bool = False
    year: int | None = None


def _normalized(title: str | None) -> str:
    return normalize_text(to_plain_text(title)) if title else ""


def determine_container_type(
    description: ContainerDescription,
) -> tuple[SeriesDescription | None, VolumeDescription | None]:
    """Sépare le conteneur d'un document en série et volume, chacun pouvant manquer.

    Un article a sa revue pour série ; sans ISSN, un conteneur qui nomme une édition datée de congrès (« 2021 ICCAS ») est un volume d'actes. Un livre, un chapitre ou un article de congrès a pour volume le livre ou le volume d'actes, et pour série la collection que désigne un ISSN : sans ISSN, sa série se reconnaît seulement entre plusieurs volumes. Un titre de collection qui a la forme d'un volume (« ICORES 2023 ») nomme le volume, à défaut d'autre titre, et sa série prend le titre de série. Un titre de volume identique à celui de la collection, sans marque d'édition, désigne la collection seule : c'est le cas d'un article de congrès paru dans une revue.
    """
    d = description
    role = container_role(d.raw_doc_type, d.source, declares_conference=d.declares_conference)
    if role is ContainerRole.JOURNAL:
        if not (d.journal_title or d.has_issn):
            return None, None
        if d.journal_title and is_dated_event_without_issn(d.journal_title, has_issn=d.has_issn):
            return None, VolumeDescription(title=d.journal_title, proceedings=True, year=d.year)
        return SeriesDescription(
            title=d.journal_title,
            issn=d.issn,
            eissn=d.eissn,
            issnl=d.issnl,
            openalex_id=d.openalex_id,
            oa_model=d.oa_model,
            rejected_issns=d.rejected_issns,
        ), None

    collection_title = d.collection_title
    volume_title = d.document_title if role is ContainerRole.BOOK else d.book_title
    if collection_title and container_level(collection_title) is ContainerLevel.VOLUME:
        volume_title = volume_title or collection_title
        collection_title = series_title(collection_title)
    series = (
        SeriesDescription(
            title=collection_title,
            issn=d.issn,
            eissn=d.eissn,
            issnl=d.issnl,
            openalex_id=d.openalex_id,
            oa_model=d.oa_model,
            rejected_issns=d.rejected_issns,
        )
        if d.has_issn
        else None
    )
    same_as_collection = bool(volume_title) and _normalized(volume_title) == _normalized(
        collection_title
    )
    if same_as_collection or not (volume_title or d.isbns or d.eisbns):
        return series, None
    return series, VolumeDescription(
        title=volume_title,
        isbns=d.isbns,
        eisbns=d.eisbns,
        proceedings=is_conference(
            d.raw_doc_type, d.source, declares_conference=d.declares_conference
        ),
        year=d.year,
    )
