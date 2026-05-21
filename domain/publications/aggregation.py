"""Agrégation cross-sources de l'aggregate Publication.

Encapsule les règles d'agrégation : à partir des `SourcePublication` attachées à une publication canonique, calcule l'état canonique de l'aggregate `Publication` et le mute en place. C'est l'inverse logique de `SourcePublication` (lecture multi-sources) → `Publication` (vue canonique).

Règles d'agrégation par type de champ :
- **Scalaires nullable** (`title`, `doi`, `doc_type`, `pub_year`, `journal_id`, `container_title`, `language`, `abstract`) : premier non-null dans l'ordre de `source_priority`.
- **`oa_status`** : le statut le plus ouvert toutes sources confondues (cf. `best_oa_status` dans `metadata`). Fallback à `OA_STATUS_UNKNOWN_DEFAULT` si toutes les sources sont silencieuses (la colonne canonique est NOT NULL).
- **`is_retracted`** : OR logique (True si au moins une source le déclare).
- **Listes** (`countries`, `keywords`) : union dédupliquée préservant l'ordre de priorité des sources.
- **JSONB `biblio`, `meta`** : fusion shallow par clé ; en cas de conflit, la source la plus prioritaire l'emporte.
- **JSONB `topics`** : composite par source — chaque source garde sa forme native sous sa propre clé (`{"openalex": [...], "scanr": ..., "theses": {...}}`).
- **`doc_type`** : premier non-null avec arbitrage des sous-types d'article (CrossRef renvoie `journal-article` indistinctement pour review / book_review / data_paper / etc. — si une source moins prioritaire propose un sous-type plus précis, on le préfère pour ne pas perdre l'information).

`title_normalized` est recalculé à partir du `title` agrégé, pas pris d'une source (les sources ne fournissent pas ce champ).
"""

from typing import Any

from domain.normalize import normalize_text
from domain.publications.doc_types import ARTICLE_SUBTYPES, map_doc_type
from domain.publications.identifiers import DOI
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT, best_oa_status
from domain.publications.publication import Publication
from domain.source_publications.source_publication import SourcePublication
from domain.types import JsonValue


def refresh_from_sources(
    pub: Publication,
    sources: list[SourcePublication],
    *,
    source_priority: tuple[str, ...],
) -> None:
    """Recalcule l'état canonique de `pub` (DOI, oa_status, méta, etc.) par agrégation de ses `sources`. Mute `pub` en place ; persistance via `repo.save(pub)` côté caller.

    Règles d'agrégation : premier non-null par `source_priority` pour les scalaires nullable, statut OA le plus ouvert toutes sources confondues, union dédupliquée des listes, fusion shallow par clé des JSONB, `topics` indexés par source.

    Précondition : `sources` non vide. Le cas orphelin (aucune source) est une décision métier qui doit être traitée par le caller avant d'appeler cette fonction (suppression de la publication via `repo.delete`).
    """
    if not sources:
        raise ValueError(
            "refresh_from_sources requiert au moins une source ; le cas orphelin est à traiter côté caller (suppression de la publication)"
        )

    rank = {s: i for i, s in enumerate(source_priority)}
    sorted_sources = sorted(sources, key=lambda s: rank.get(s.source, 99))

    new_title = first_non_null(sorted_sources, "title")
    pub.title = new_title if new_title is not None else pub.title
    pub.title_normalized = normalize_text(pub.title) if pub.title else None
    pub.doc_type = arbitrate_doc_type_with_article_subtype(sorted_sources)
    pub.pub_year = first_non_null(sorted_sources, "pub_year") or pub.pub_year

    new_doi_str = first_non_null(sorted_sources, "doi")
    pub.doi = DOI(new_doi_str) if new_doi_str else None

    pub.journal_id = first_non_null(sorted_sources, "journal_id")
    pub.oa_status = best_oa_status(s.oa_status for s in sorted_sources) or OA_STATUS_UNKNOWN_DEFAULT
    pub.container_title = first_non_null(sorted_sources, "container_title")
    pub.language = first_non_null(sorted_sources, "language")
    pub.abstract = first_non_null(sorted_sources, "abstract")
    pub.keywords = tuple(merge_lists_dedup_ci(sorted_sources, "keywords") or ())
    pub.countries = tuple(merge_lists_dedup_ci(sorted_sources, "countries") or ())
    pub.topics = topics_by_source(sorted_sources)
    pub.biblio = shallow_merge_jsonb(sorted_sources, "biblio")
    pub.meta = shallow_merge_jsonb(sorted_sources, "meta")
    pub.is_retracted = any(s.is_retracted for s in sorted_sources if s.is_retracted)


# ── Helpers publics ────────────────────────────────────────────────


def first_non_null(sources: list[SourcePublication], attr: str) -> Any:
    """Premier `getattr(source, attr)` non-null dans l'ordre des `sources`. None si tous absents.

    Retour `Any` justifié : type polymorphique selon `attr` (str pour
    `title`, int pour `pub_year`, list pour `keywords`, …). Typer un
    générique via TypeVar serait excessif pour 1 helper utilisé en
    interne par `refresh_from_sources`.
    """
    for s in sources:
        v = getattr(s, attr)
        if v is not None:
            return v
    return None


def merge_lists_dedup_ci(sources: list[SourcePublication], attr: str) -> list[Any] | None:
    """Union dédupliquée des listes `source.<attr>`. Déduplication case-insensitive pour les strings, sinon par valeur. Préserve l'ordre d'apparition. None si toutes vides/null.

    `list[Any]` justifié : les listes consommées sont `list[str]` (`keywords`,
    `countries`, …) en pratique, mais `getattr` est polymorphique — même
    justification que `first_non_null`.
    """
    seen: set[Any] = set()
    result: list[Any] = []
    for s in sources:
        for item in getattr(s, attr) or ():
            key = item.lower() if isinstance(item, str) else item
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result or None


def shallow_merge_jsonb(sources: list[SourcePublication], attr: str) -> dict[str, JsonValue] | None:
    """Fusion shallow par clé pour `meta` / `biblio`. La première source à fournir une clé l'emporte (cohérent avec « premier non-null ») ; les clés sont généralement orthogonales entre sources."""
    merged: dict[str, JsonValue] = {}
    for s in sources:
        d = getattr(s, attr)
        if isinstance(d, dict):
            for k, v in d.items():
                if k not in merged:
                    merged[k] = v
    return merged or None


def topics_by_source(sources: list[SourcePublication]) -> dict[str, JsonValue] | None:
    """Indexe les `topics` par source. Schémas radicalement différents par source — chacun reste sous sa propre clé pour préserver la forme native (liste hiérarchique OpenAlex, dict ScanR, etc.)."""
    out: dict[str, JsonValue] = {}
    for s in sources:
        if s.topics:
            out[s.source] = s.topics
    return out or None


def arbitrate_doc_type_with_article_subtype(sources: list[SourcePublication]) -> str:
    """Choix du `doc_type` canonique : premier non-null dans l'ordre de priorité, avec exception pour les sous-types d'article.

    CrossRef (priorité 2) renvoie `journal-article` indistinctement pour tous les sous-types (review, book_review, data_paper, poster, conference_paper, editorial, letter, erratum, retraction). Si une source moins prioritaire propose un de ces sous-types plus précis, on le préfère pour ne pas perdre l'information.
    """
    article_subtype_present: str | None = None
    for s in sources:
        if not s.doc_type:
            continue
        mapped = map_doc_type(s.doc_type, s.source)
        if mapped in ARTICLE_SUBTYPES:
            article_subtype_present = mapped
            break

    for s in sources:
        if not s.doc_type:
            continue
        mapped = map_doc_type(s.doc_type, s.source)
        if mapped == "article" and article_subtype_present:
            return article_subtype_present
        return mapped
    return "other"
