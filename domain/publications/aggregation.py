"""Métadonnées d'une publication, agrégées depuis ses enregistrements sources."""

from collections.abc import Mapping
from typing import cast

from domain.normalize import normalize_text
from domain.platforms.registry import is_publisher_platform_prefix
from domain.publications.conference import arbitrate_conference
from domain.publications.doc_types import ARTICLE_SUBTYPES, DocType
from domain.publications.identifiers import DOI
from domain.publications.licenses import DEPOSIT_LICENSE_SOURCE, publisher_license_sources
from domain.publications.metadata import publication_oa_status
from domain.publications.publication import Publication
from domain.publishers.attribution import publication_publisher
from domain.source_records.keys import anchor_of, doi_anchors
from domain.source_records.source_record import SourceRecord
from domain.sources.registry import Source
from domain.types import JsonValue, as_int, as_str


def refresh_from_sources(
    publication: Publication,
    sources: list[SourceRecord],
    *,
    source_priority: tuple[str, ...],
    monograph_serials: Mapping[int, int | None] | None = None,
    unpaywall: Mapping[str, str] | None = None,
) -> None:
    """Recalcule sur place les métadonnées de `publication` depuis ses enregistrements sources. `sources` est non vide : une publication sans enregistrement source se supprime. L'éditeur se pose ensuite, par `assign_publisher`.

    - Champs simples : première valeur non nulle dans l'ordre de `source_priority`. Sans revue dans aucune source, la publication prend la collection de sa monographie (`monograph_serials`).
    - Type de document : `arbitrate_doc_type_with_article_subtype`, puis `arbitrate_conference`.
    - Statut open access : le plus ouvert des sources, ou le verdict d'Unpaywall sur le DOI (`unpaywall`, par DOI).
    - Licence : celle de la version éditeur (`publisher_license_sources`). Licence de dépôt : celle du fichier déposé dans HAL.
    - Rétractation : déclarée par une source au moins.
    - Mots-clés et pays : union sans doublon.
    - `biblio` et `source_extras` : fusion par clé, la source prioritaire l'emporte.
    - `topics` : sous la clé de chaque source.
    """
    if not sources:
        raise ValueError(
            "refresh_from_sources requiert au moins une source ; le cas orphelin est à traiter côté caller (suppression de la publication)"
        )

    sorted_sources = prioritized(sources, source_priority)

    new_title = as_str(first_non_null(sorted_sources, "title"))
    publication.title = new_title if new_title is not None else publication.title
    publication.title_normalized = normalize_text(publication.title) if publication.title else None
    publication.doc_type = arbitrate_conference(
        arbitrate_doc_type_with_article_subtype(sorted_sources), sorted_sources
    )
    publication.publication_year = (
        as_int(first_non_null(sorted_sources, "publication_year")) or publication.publication_year
    )

    new_doi_str = publication_doi(sorted_sources)
    publication.doi = DOI(new_doi_str) if new_doi_str else None

    publication.serial_id = as_int(first_non_null(sorted_sources, "serial_id"))
    publication.monograph_id = as_int(first_non_null(sorted_sources, "monograph_id"))
    if publication.serial_id is None and publication.monograph_id is not None and monograph_serials:
        publication.serial_id = monograph_serials.get(publication.monograph_id)
    publication.oa_status = publication_oa_status(
        sorted_sources,
        unpaywall.get(publication.doi.value) if publication.doi and unpaywall else None,
    )
    publication.license = license_by_source(
        sorted_sources, publisher_license_sources(publication.doc_type)
    )
    publication.deposit_license = license_by_source(sorted_sources, (DEPOSIT_LICENSE_SOURCE,))
    publication.container_title = as_str(first_non_null(sorted_sources, "container_title"))
    publication.language = as_str(first_non_null(sorted_sources, "language"))
    publication.abstract = as_str(first_non_null(sorted_sources, "abstract"))
    publication.keywords = _textes(merge_lists_dedup_ci(sorted_sources, "keywords"))
    publication.countries = _textes(merge_lists_dedup_ci(sorted_sources, "countries"))
    publication.topics = topics_by_source(sorted_sources)
    publication.biblio = shallow_merge_jsonb(sorted_sources, "biblio")
    publication.source_extras = shallow_merge_jsonb(sorted_sources, "source_extras")
    publication.is_retracted = any(s.is_retracted for s in sorted_sources if s.is_retracted)


def assign_publisher(
    publication: Publication,
    sources: list[SourceRecord],
    *,
    source_priority: tuple[str, ...],
    prefix_publishers: Mapping[str, int] | None = None,
) -> None:
    """Pose l'éditeur de `publication` d'après son type de document, son DOI et ses `sources`. `prefix_publishers` : titulaire de chaque préfixe DOI Crossref."""
    prefix = publication.doi.prefix.value if publication.doi else None
    publication.publisher_id = publication_publisher(
        publication.doc_type,
        (prefix_publishers or {}).get(prefix) if prefix else None,
        (s.publisher_id for s in prioritized(sources, source_priority)),
        platform_prefix=prefix is not None and is_publisher_platform_prefix(prefix),
    )


def publication_doi(sources: list[SourceRecord]) -> str | None:
    """DOI d'une publication : l'ancre de ses enregistrements sources (`doi_anchors`). Entre plusieurs ancres, celle du premier enregistrement source de `sources` qui en rejoint une."""
    anchors = doi_anchors(s.dois for s in sources)
    if len(anchors) == 1:
        return next(iter(anchors))
    return next((a for s in sources if (a := anchor_of(s.dois, anchors)) is not None), None)


def prioritized(
    sources: list[SourceRecord], source_priority: tuple[str, ...]
) -> list[SourceRecord]:
    """`sources` dans l'ordre de `source_priority`."""
    rank = {s: i for i, s in enumerate(source_priority)}
    return sorted(sources, key=lambda s: rank.get(s.source, 99))


def _textes(valeurs: list[JsonValue] | None) -> tuple[str, ...]:
    """Valeurs textuelles d'une liste fusionnée ; les autres sont écartées."""
    return tuple(texte for v in valeurs or () if (texte := as_str(v)))


def license_by_source(sources: list[SourceRecord], order: tuple[Source, ...]) -> str | None:
    """Première licence des `sources` dans l'ordre de sources `order`, puis dans l'ordre de `sources`."""
    for source in order:
        for s in sources:
            if s.source == source and s.license:
                return s.license
    return None


def first_non_null(sources: list[SourceRecord], attr: str) -> JsonValue:
    """Première valeur non nulle de l'attribut `attr` dans l'ordre des `sources`, ou `None`."""
    for s in sources:
        v = getattr(s, attr)
        if v is not None:
            # Valeur de colonne, donc valeur JSON, que le vérificateur de types ne déduit pas d'un `getattr`.
            return cast("JsonValue", v)
    return None


def merge_lists_dedup_ci(sources: list[SourceRecord], attr: str) -> list[JsonValue] | None:
    """Union des listes de l'attribut `attr`, sans doublon, dans l'ordre d'apparition. Le texte se compare sans la casse. `None` si toutes les listes sont vides."""
    seen: set[JsonValue] = set()
    result: list[JsonValue] = []
    for s in sources:
        for item in getattr(s, attr) or ():
            key = item.lower() if isinstance(item, str) else item
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result or None


def shallow_merge_jsonb(sources: list[SourceRecord], attr: str) -> dict[str, JsonValue] | None:
    """Fusion par clé des objets de l'attribut `attr`. La première source qui donne une clé l'emporte."""
    merged: dict[str, JsonValue] = {}
    for s in sources:
        d = getattr(s, attr)
        if isinstance(d, dict):
            for k, v in d.items():
                if k not in merged:
                    merged[k] = v
    return merged or None


def topics_by_source(
    sources: list[SourceRecord],
) -> dict[str, JsonValue] | None:
    """`topics` de chaque source, sous la clé de la source : leur forme diffère d'une source à l'autre."""
    out: dict[str, JsonValue] = {}
    for s in sources:
        if s.topics:
            out[s.source] = s.topics
    return out or None


def arbitrate_doc_type_with_article_subtype(sources: list[SourceRecord]) -> str:
    """Type de document : le premier non nul dans l'ordre des `sources`. Le premier sous-type d'article, toutes sources confondues, l'emporte sur `article`, que Crossref donne pour tous les sous-types. Un `data_paper` déclaré par HAL seul compte pour `article`."""
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
    """`doc_type` de `source`, ramené à `article` pour un `data_paper` de HAL qu'aucune autre source ne déclare."""
    if (
        source.source == Source.HAL
        and source.doc_type == DocType.DATA_PAPER
        and not any(s.source != Source.HAL and s.doc_type == DocType.DATA_PAPER for s in sources)
    ):
        return DocType.ARTICLE
    return source.doc_type
