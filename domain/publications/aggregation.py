"""Métadonnées d'une publication, agrégées depuis ses enregistrements sources."""

from collections.abc import Iterable, Mapping

from domain.normalize import normalize_text
from domain.platforms.registry import is_publisher_platform_prefix
from domain.publications.conference import arbitrate_conference
from domain.publications.dates import arbitrate_publication_date
from domain.publications.doc_types import ARTICLE_SUBTYPES, DocType
from domain.publications.identifiers import DOI
from domain.publications.licenses import DEPOSIT_LICENSE_SOURCE, publisher_license_sources
from domain.publications.publication import Publication
from domain.publishers.attribution import publication_publisher
from domain.source_records.keys import anchor_of, deposit_anchors, doi_anchors
from domain.source_records.source_record import SourceRecord
from domain.sources.registry import Source
from domain.types import JsonValue


def refresh_from_sources(
    publication: Publication,
    sources: list[SourceRecord],
    *,
    source_priority: tuple[str, ...],
    monograph_serials: Mapping[int, int | None] | None = None,
) -> None:
    """Recalcule sur place les métadonnées de `publication` depuis ses enregistrements sources. L'éditeur se pose ensuite, par `assign_publisher`, et le statut open access d'après les copies (`domain.publications.open_access`).

    - DOI : `publication_doi`.
    - Champs simples : première valeur non nulle dans l'ordre d'arbitrage (`_arbitration_order`). Sans revue dans aucune source, la publication prend la collection de sa monographie (`monograph_serials`).
    - Type de document : `arbitrate_doc_type_with_article_subtype`, puis `arbitrate_conference`.
    - Date de publication : `arbitrate_publication_date` ; l'année en dérive.
    - Licence : celle de la version éditeur (`publisher_license_sources`). Licence de dépôt : celle du fichier déposé dans HAL.
    - Rétractation : déclarée par une source au moins.
    - Indicateurs de citation : ceux du premier enregistrement source OpenAlex dans l'ordre d'arbitrage. Le nombre de citations et le FWCI décrivent ainsi la même œuvre, comptée dans la même base.
    - Mots-clés et pays : union sans doublon.
    - `biblio` et `source_extras` : fusion par clé, la source prioritaire l'emporte.

    Raises:
        ValueError: `sources` vide ; une publication sans enregistrement source se supprime.
    """
    if not sources:
        raise ValueError(
            "refresh_from_sources requiert au moins une source ; le cas orphelin est à traiter côté caller (suppression de la publication)"
        )

    new_doi_str = publication_doi(_prioritized(sources, source_priority))
    publication.doi = DOI(new_doi_str) if new_doi_str else None
    sorted_sources = _arbitration_order(sources, source_priority)

    new_title = _first(s.title for s in sorted_sources)
    publication.title = new_title if new_title is not None else publication.title
    publication.title_normalized = normalize_text(publication.title) if publication.title else None
    publication.doc_type = arbitrate_conference(
        arbitrate_doc_type_with_article_subtype(sorted_sources), sorted_sources
    )
    publication.publication_date = (
        arbitrate_publication_date(
            [s.publication_date for s in sorted_sources if s.publication_date]
        )
        or publication.publication_date
    )
    if publication.publication_date is not None:
        publication.publication_year = publication.publication_date.year

    publication.serial_id = _first(s.serial_id for s in sorted_sources)
    publication.monograph_id = _first(s.monograph_id for s in sorted_sources)
    if publication.serial_id is None and publication.monograph_id is not None and monograph_serials:
        publication.serial_id = monograph_serials.get(publication.monograph_id)
    publication.license = _license_by_source(
        sorted_sources, publisher_license_sources(publication.doc_type)
    )
    publication.deposit_license = _license_by_source(sorted_sources, (DEPOSIT_LICENSE_SOURCE,))
    publication.container_title = _first(s.container_title for s in sorted_sources)
    publication.language = _first(s.language for s in sorted_sources)
    publication.abstract = _first(s.abstract for s in sorted_sources)
    publication.keywords = _union_ci(s.keywords for s in sorted_sources)
    publication.countries = _union_ci(s.countries for s in sorted_sources)
    publication.biblio = _merge_by_key(s.biblio for s in sorted_sources)
    publication.source_extras = _merge_by_key(s.source_extras for s in sorted_sources)
    publication.is_retracted = any(s.is_retracted for s in sorted_sources if s.is_retracted)
    publication.impact = next(
        (s.impact for s in sorted_sources if s.source == Source.OPENALEX), None
    )


def assign_publisher(
    publication: Publication,
    sources: list[SourceRecord],
    *,
    source_priority: tuple[str, ...],
    prefix_publishers: Mapping[str, int] | None = None,
) -> None:
    """Pose l'éditeur de `publication` d'après son type de document, son DOI et ses `sources`.

    Args:
        prefix_publishers: titulaire de chaque préfixe DOI Crossref.
    """
    prefix = publication.doi.prefix.value if publication.doi else None
    publication.publisher_id = publication_publisher(
        publication.doc_type,
        (prefix_publishers or {}).get(prefix) if prefix else None,
        (s.publisher_id for s in _arbitration_order(sources, source_priority)),
        platform_prefix=prefix is not None and is_publisher_platform_prefix(prefix),
    )


def publication_doi(sources: list[SourceRecord]) -> str | None:
    """Renvoie le DOI d'une publication : l'ancre de ses enregistrements sources (`doi_anchors`), à défaut un DOI de dépôt (`deposit_anchors`). Entre plusieurs candidats, celui du premier enregistrement source de `sources` qui en rejoint un."""
    candidates = doi_anchors(s.dois for s in sources) or deposit_anchors(s.dois for s in sources)
    if len(candidates) == 1:
        return next(iter(candidates))
    return next((a for s in sources if (a := anchor_of(s.dois, candidates)) is not None), None)


def _prioritized(
    sources: list[SourceRecord], source_priority: tuple[str, ...]
) -> list[SourceRecord]:
    """Trie `sources` dans l'ordre de `source_priority`."""
    rank = {s: i for i, s in enumerate(source_priority)}
    return sorted(sources, key=lambda s: rank.get(s.source, 99))


def _arbitration_order(
    sources: list[SourceRecord], source_priority: tuple[str, ...]
) -> list[SourceRecord]:
    """Trie `sources` dans l'ordre de `source_priority`. Dans une publication qui a une version publiée (`_has_published_version`), les enregistrements sources preprint passent après les autres."""
    ordered = _prioritized(sources, source_priority)
    if not _has_published_version(sources):
        return ordered
    return sorted(ordered, key=lambda s: s.doc_type == DocType.PREPRINT)


def _has_published_version(sources: list[SourceRecord]) -> bool:
    """Vrai si une publication a une version publiée : une ancre (`doi_anchors`), ou la revue ou la monographie d'un enregistrement source typé autrement que preprint."""
    if doi_anchors(s.dois for s in sources):
        return True
    return any(
        s.doc_type not in (None, DocType.PREPRINT)
        and (s.serial_id is not None or s.monograph_id is not None)
        for s in sources
    )


def _license_by_source(sources: list[SourceRecord], order: tuple[Source, ...]) -> str | None:
    """Renvoie la première licence des `sources` dans l'ordre de sources `order`, puis dans l'ordre de `sources`."""
    for source in order:
        for s in sources:
            if s.source == source and s.license:
                return s.license
    return None


def _first[T](values: Iterable[T | None]) -> T | None:
    """Renvoie la première valeur non nulle, ou `None`."""
    return next((v for v in values if v is not None), None)


def _union_ci(lists: Iterable[Iterable[str]]) -> tuple[str, ...]:
    """Renvoie l'union des listes, sans doublon, dans l'ordre d'apparition. Le texte se compare sans la casse."""
    seen: set[str] = set()
    result: list[str] = []
    for items in lists:
        for item in items:
            if item.lower() not in seen:
                seen.add(item.lower())
                result.append(item)
    return tuple(result)


def _merge_by_key(
    objects: Iterable[Mapping[str, JsonValue] | None],
) -> dict[str, JsonValue] | None:
    """Fusionne les objets par clé. Le premier objet qui donne une clé l'emporte. `None` sans aucune clé."""
    merged: dict[str, JsonValue] = {}
    for obj in objects:
        for k, v in (obj or {}).items():
            merged.setdefault(k, v)
    return merged or None


def arbitrate_doc_type_with_article_subtype(sources: list[SourceRecord]) -> str:
    """Arbitre le type de document : le premier non nul dans l'ordre des `sources`. Le premier sous-type d'article, toutes sources confondues, l'emporte sur `article`, donné par Crossref pour tous les sous-types. Un `data_paper` déclaré par HAL seul compte pour `article`."""
    doc_types = [_corroborated_doc_type(s, sources) for s in sources]
    article_subtype_present = next((t for t in doc_types if t in ARTICLE_SUBTYPES), None)

    for doc_type in doc_types:
        if not doc_type:
            continue
        if doc_type == DocType.ARTICLE and article_subtype_present:
            return article_subtype_present
        return doc_type
    return "other"


def _corroborated_doc_type(source: SourceRecord, sources: list[SourceRecord]) -> str | None:
    """Renvoie le `doc_type` de `source`, ramené à `article` pour un `data_paper` de HAL déclaré par aucune autre source."""
    if (
        source.source == Source.HAL
        and source.doc_type == DocType.DATA_PAPER
        and not any(s.source != Source.HAL and s.doc_type == DocType.DATA_PAPER for s in sources)
    ):
        return DocType.ARTICLE
    return source.doc_type
