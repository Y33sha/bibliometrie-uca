"""Agrégation cross-sources de l'aggregate Publication.

Encapsule les règles d'agrégation : à partir des `source_records` attachées à une publication canonique (lues via `SourceRecord`), calcule l'état canonique de l'aggregate `Publication` et le mute en place. C'est l'inverse logique de la lecture multi-sources → `Publication` (vue canonique).

Règles d'agrégation par type de champ :
- **Scalaires nullable** (`title`, `doi`, `doc_type`, `publication_year`, `journal_id`, `monograph_id`, `container_title`, `language`, `abstract`) : premier non-null dans l'ordre de `source_priority`. Sans `journal_id` d'aucune source, la publication prend celui de sa monographie, sa collection.
- **`oa_status`** : le statut le plus ouvert des sources, ou le verdict d'Unpaywall sur le DOI de la publication (`publication_oa_status` dans `metadata`).
- **`license`** : licence de la version éditeur, première non nulle dans l'ordre de `publisher_license_sources` (Crossref, OpenAlex, scanR, DataCite ; DataCite en tête pour un jeu de données ou un logiciel). **`deposit_license`** : licence du fichier déposé dans HAL.
- **`is_retracted`** : OR logique (True si au moins une source le déclare).
- **Listes** (`countries`, `keywords`) : union dédupliquée préservant l'ordre de priorité des sources.
- **JSONB `biblio`, `source_extras`** : fusion shallow par clé ; en cas de conflit, la source la plus prioritaire l'emporte.
- **JSONB `topics`** : composite par source — chaque source garde sa forme native sous sa propre clé (`{"openalex": [...], "scanr": ..., "theses": {...}}`).
- **`doc_type`** : premier non-null, un sous-type d'article d'une source moins prioritaire l'emportant sur `article` (cf. `arbitrate_doc_type_with_article_subtype`), puis arbitrage entre communication et texte d'actes (`arbitrate_conference`).
- **`publisher_id`** : posé par `assign_publisher`, une fois le type de document corrigé (`domain.publishers.attribution`).

Priorité d'ordre : les enregistrements canoniques passent avant les formes secondaires convergées (`secondary_ids` — pièce, version ou variante dont le DOI a été substitué par celui de l'œuvre canonique), afin que les scalaires descriptifs (titre en tête) viennent de l'enregistrement qui porte nativement le DOI, pas d'une pièce. La priorité de source départage à l'intérieur de chaque groupe.

`title_normalized` est recalculé à partir du `title` agrégé, pas pris d'une source (les sources ne fournissent pas ce champ).
"""

from collections.abc import Mapping
from typing import cast

from domain.normalize import normalize_text
from domain.publications.conference import arbitrate_conference
from domain.publications.doc_types import ARTICLE_SUBTYPES, DocType
from domain.publications.identifiers import DOI
from domain.publications.licenses import DEPOSIT_LICENSE_SOURCE, publisher_license_sources
from domain.publications.metadata import publication_oa_status
from domain.publications.publication import Publication
from domain.publishers.attribution import publication_publisher
from domain.source_records.source_record import SourceRecord
from domain.sources.registry import Source
from domain.types import JsonValue, as_int, as_str


def refresh_from_sources(
    publication: Publication,
    sources: list[SourceRecord],
    *,
    source_priority: tuple[str, ...],
    secondary_ids: frozenset[int] = frozenset(),
    monograph_journals: Mapping[int, int | None] | None = None,
    unpaywall: Mapping[str, str] | None = None,
) -> None:
    """Recalcule l'état de `publication` (DOI, oa_status, méta, etc.) par agrégation de ses `sources`. Mute `publication` en place ; persistance via `repo.save(publication)` côté caller.

    Règles d'agrégation : premier non-null par `source_priority` pour les scalaires nullable, statut OA tiré des sources et du verdict d'Unpaywall (`publication_oa_status`), union dédupliquée des listes, fusion shallow par clé des JSONB, `topics` indexés par source.

    `secondary_ids` liste les `source_records` qui décrivent une **forme secondaire** de l'œuvre : une pièce, une version ou une variante dont la correction de convergence a remplacé le DOI par celui de l'œuvre. Elles passent en fin de priorité : les scalaires descriptifs (titre en tête) viennent de l'enregistrement dont c'est le DOI d'origine. Les listes restent unionnées toutes sources confondues : une pièce peut contenir un mot-clé légitime.

    `monograph_journals` donne l'entrée de `journals` de chaque monographie des sources, sa collection : une publication dont aucune source ne porte de `journal_id` prend celle de sa monographie.

    `unpaywall` donne le verdict d'Unpaywall des DOI des sources que connaît Unpaywall.

    Précondition : `sources` non vide. Le cas orphelin (aucune source) est une décision métier qui doit être traitée par le caller avant d'appeler cette fonction (suppression de la publication via `repo.delete`).
    """
    if not sources:
        raise ValueError(
            "refresh_from_sources requiert au moins une source ; le cas orphelin est à traiter côté caller (suppression de la publication)"
        )

    sorted_sources = prioritized(sources, source_priority, secondary_ids)

    new_title = as_str(first_non_null(sorted_sources, "title"))
    publication.title = new_title if new_title is not None else publication.title
    publication.title_normalized = normalize_text(publication.title) if publication.title else None
    publication.doc_type = arbitrate_conference(
        arbitrate_doc_type_with_article_subtype(sorted_sources), sorted_sources
    )
    publication.publication_year = (
        as_int(first_non_null(sorted_sources, "publication_year")) or publication.publication_year
    )

    new_doi_str = as_str(first_non_null(sorted_sources, "doi"))
    publication.doi = DOI(new_doi_str) if new_doi_str else None

    publication.journal_id = as_int(first_non_null(sorted_sources, "journal_id"))
    publication.monograph_id = as_int(first_non_null(sorted_sources, "monograph_id"))
    if (
        publication.journal_id is None
        and publication.monograph_id is not None
        and monograph_journals
    ):
        publication.journal_id = monograph_journals.get(publication.monograph_id)
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
    secondary_ids: frozenset[int] = frozenset(),
    prefix_publishers: Mapping[str, int] | None = None,
) -> None:
    """Pose l'éditeur de `publication` d'après son type de document, son DOI et ses `sources`.

    `prefix_publishers` donne le titulaire de chaque préfixe DOI Crossref.
    """
    prefix = publication.doi.prefix.value if publication.doi else None
    publication.publisher_id = publication_publisher(
        publication.doc_type,
        (prefix_publishers or {}).get(prefix) if prefix else None,
        (s.publisher_id for s in prioritized(sources, source_priority, secondary_ids)),
    )


# ── Helpers publics ────────────────────────────────────────────────


def prioritized(
    sources: list[SourceRecord], source_priority: tuple[str, ...], secondary_ids: frozenset[int]
) -> list[SourceRecord]:
    """`sources` dans l'ordre de l'agrégation : formes canoniques avant formes secondaires, puis ordre de `source_priority`."""
    rank = {s: i for i, s in enumerate(source_priority)}
    return sorted(sources, key=lambda s: (s.id in secondary_ids, rank.get(s.source, 99)))


def _textes(valeurs: list[JsonValue] | None) -> tuple[str, ...]:
    """Valeurs textuelles d'une liste fusionnée : mots-clés et pays sont du texte, le reste ne s'écrit pas."""
    return tuple(texte for v in valeurs or () if (texte := as_str(v)))


def license_by_source(sources: list[SourceRecord], order: tuple[Source, ...]) -> str | None:
    """Première licence des `sources` dans l'ordre de sources `order`, puis dans l'ordre de `sources`."""
    for source in order:
        for s in sources:
            if s.source == source and s.license:
                return s.license
    return None


def first_non_null(sources: list[SourceRecord], attr: str) -> JsonValue:
    """Premier `getattr(source, attr)` non-null dans l'ordre des `sources`. None si tous absents.

    La valeur rendue dépend de l'attribut lu — texte pour le titre, entier pour l'année, liste pour les mots-clés. Ce sont toutes des valeurs de colonne, donc des valeurs JSON : l'appelant les repose telles quelles sur la publication canonique.
    """
    for s in sources:
        v = getattr(s, attr)
        if v is not None:
            # `getattr` sur un nom calculé rend une valeur inconnue du vérificateur ; le
            # docstring dit d'où elle vient et ce qu'elle vaut.
            return cast("JsonValue", v)
    return None


def merge_lists_dedup_ci(sources: list[SourceRecord], attr: str) -> list[JsonValue] | None:
    """Union dédupliquée des listes `source.<attr>`. Déduplication insensible à la casse pour le texte, par valeur sinon. Préserve l'ordre d'apparition. None si toutes vides ou nulles.

    Les listes consommées sont textuelles en pratique — mots-clés, pays —, mais l'attribut est lu par son nom : le type est celui d'une valeur de colonne.
    """
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
    """Fusion shallow par clé pour `source_extras` / `biblio`. La première source à fournir une clé l'emporte (cohérent avec « premier non-null ») ; les clés sont généralement orthogonales entre sources."""
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
    """Indexe les `topics` par source. Schémas radicalement différents par source — chacun reste sous sa propre clé pour préserver la forme native (liste hiérarchique OpenAlex, dict ScanR, etc.)."""
    out: dict[str, JsonValue] = {}
    for s in sources:
        if s.topics:
            out[s.source] = s.topics
    return out or None


def arbitrate_doc_type_with_article_subtype(sources: list[SourceRecord]) -> str:
    """Choix du `doc_type` canonique : premier non-null dans l'ordre de priorité, avec exception pour les sous-types d'article.

    Les `doc_type` lus sont traduits par la normalisation et corrigés par la phase `metadata_correction`.

    CrossRef (priorité 2) renvoie `journal-article` pour tous les sous-types (review, book_review, data_paper, poster, conference_paper, editorial, letter, erratum, retraction). Le premier sous-type d'article, toutes sources confondues, l'emporte sur `article`. Un `data_paper` déclaré par HAL seul compte pour `article`.
    """
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
