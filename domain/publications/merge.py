"""Algorithme de fusion multi-sources des publications.

Encapsule les règles d'agrégation cross-sources : à partir des lignes `source_publications` attachées à une publication, calcule l'état canonique de l'aggregate `Publication` et le mute en place. C'est l'inverse logique de `SourcePublication` (lecture multi-sources) → `Publication` (vue canonique).

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

from domain.json_types import JsonValue
from domain.normalize import normalize_text
from domain.publications.doc_types import ARTICLE_SUBTYPES, map_doc_type
from domain.publications.identifiers import DOI
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT, best_oa_status
from domain.publications.publication import Publication


def merge_source_rows(
    pub: Publication,
    rows: list[dict[str, Any]],
    *,
    source_priority: tuple[str, ...],
) -> None:
    """Mute `pub` avec l'agrégation cross-sources de `rows`.

    `rows` est la liste des `source_publications` attachées à `pub`, telle que renvoyée par `repo.get_source_rows(pub.id)`. `source_priority` donne l'ordre de prééminence des sources pour les règles « premier non-null gagne ».

    Mutation sur les attributs canoniques de `pub`. Le `pub.id` n'est pas touché, ni les `authorships`. Persistance via `repo.save(pub)` côté caller.

    Si `rows` est vide (aucune source attachée), la fonction est un no-op.
    """
    if not rows:
        return

    rank = {s: i for i, s in enumerate(source_priority)}
    rows_sorted = sorted(rows, key=lambda r: rank.get(r["source"], 99))

    new_title = first_non_null(rows_sorted, "title")
    pub.title = new_title if new_title is not None else pub.title
    pub.title_normalized = normalize_text(pub.title) if pub.title else None
    pub.doc_type = arbitrate_doc_type_with_article_subtype(rows_sorted)
    pub.pub_year = first_non_null(rows_sorted, "pub_year") or pub.pub_year

    new_doi_str = first_non_null(rows_sorted, "doi")
    pub.doi = DOI(new_doi_str) if new_doi_str else None

    pub.journal_id = first_non_null(rows_sorted, "journal_id")
    pub.oa_status = best_oa_status(r["oa_status"] for r in rows_sorted) or OA_STATUS_UNKNOWN_DEFAULT
    pub.container_title = first_non_null(rows_sorted, "container_title")
    pub.language = first_non_null(rows_sorted, "language")
    pub.abstract = first_non_null(rows_sorted, "abstract")
    pub.keywords = tuple(merge_lists_dedup_ci(rows_sorted, "keywords") or ())
    pub.countries = tuple(merge_lists_dedup_ci(rows_sorted, "countries") or ())
    pub.topics = topics_by_source(rows_sorted)
    pub.biblio = shallow_merge_jsonb(rows_sorted, "biblio")
    pub.meta = shallow_merge_jsonb(rows_sorted, "meta")
    pub.is_retracted = any(r["is_retracted"] for r in rows_sorted if r["is_retracted"])


# ── Helpers publics ────────────────────────────────────────────────


def first_non_null(rows: list[dict[str, Any]], field: str) -> Any:
    """Premier `row[field]` non-null dans l'ordre des `rows`. None si tous absents."""
    for r in rows:
        v = r[field]
        if v is not None:
            return v
    return None


def merge_lists_dedup_ci(rows: list[dict[str, Any]], field: str) -> list[Any] | None:
    """Union dédupliquée des listes `row[field]`. Déduplication case-insensitive pour les strings, sinon par valeur. Préserve l'ordre d'apparition. None si toutes vides/null."""
    seen: set[Any] = set()
    result: list[Any] = []
    for r in rows:
        for item in r[field] or []:
            key = item.lower() if isinstance(item, str) else item
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result or None


def shallow_merge_jsonb(rows: list[dict[str, Any]], field: str) -> dict[str, JsonValue] | None:
    """Fusion shallow par clé pour `meta` / `biblio`. La première source à fournir une clé l'emporte (cohérent avec « premier non-null ») ; les clés sont généralement orthogonales entre sources."""
    merged: dict[str, JsonValue] = {}
    for r in rows:
        d = r[field]
        if isinstance(d, dict):
            for k, v in d.items():
                if k not in merged:
                    merged[k] = v
    return merged or None


def topics_by_source(rows: list[dict[str, Any]]) -> dict[str, JsonValue] | None:
    """Indexe les `topics` par source. Schémas radicalement différents par source — chacun reste sous sa propre clé pour préserver la forme native (liste hiérarchique OpenAlex, dict ScanR, etc.)."""
    out: dict[str, JsonValue] = {}
    for r in rows:
        topics = r["topics"]
        if topics:
            out[r["source"]] = topics
    return out or None


def arbitrate_doc_type_with_article_subtype(rows: list[dict[str, Any]]) -> str:
    """Choix du `doc_type` canonique : premier non-null dans l'ordre de priorité, avec exception pour les sous-types d'article.

    CrossRef (priorité 2) renvoie `journal-article` indistinctement pour tous les sous-types (review, book_review, data_paper, poster, conference_paper, editorial, letter, erratum, retraction). Si une source moins prioritaire propose un de ces sous-types plus précis, on le préfère pour ne pas perdre l'information.
    """
    article_subtype_present: str | None = None
    for r in rows:
        if not r["doc_type"]:
            continue
        mapped = map_doc_type(r["doc_type"], r["source"])
        if mapped in ARTICLE_SUBTYPES:
            article_subtype_present = mapped
            break

    for r in rows:
        if not r["doc_type"]:
            continue
        mapped = map_doc_type(r["doc_type"], r["source"])
        if mapped == "article" and article_subtype_present:
            return article_subtype_present
        return mapped
    return "other"
