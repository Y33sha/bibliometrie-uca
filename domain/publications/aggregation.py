"""Agrégation cross-sources de l'aggregate Publication.

Encapsule les règles d'agrégation : à partir des `source_publications` attachées à une publication canonique (lues via `SourcePublication`), calcule l'état canonique de l'aggregate `Publication` et le mute en place. C'est l'inverse logique de la lecture multi-sources → `Publication` (vue canonique).

Règles d'agrégation par type de champ :
- **Scalaires nullable** (`title`, `doi`, `doc_type`, `pub_year`, `journal_id`, `container_title`, `language`, `abstract`) : premier non-null dans l'ordre de `source_priority`.
- **`oa_status`** : le statut le plus ouvert toutes sources confondues (cf. `best_oa_status` dans `metadata`). Fallback à `OA_STATUS_UNKNOWN_DEFAULT` si toutes les sources sont silencieuses (la colonne canonique est NOT NULL).
- **`is_retracted`** : OR logique (True si au moins une source le déclare).
- **Listes** (`countries`, `keywords`) : union dédupliquée préservant l'ordre de priorité des sources.
- **JSONB `biblio`, `meta`** : fusion shallow par clé ; en cas de conflit, la source la plus prioritaire l'emporte.
- **JSONB `topics`** : composite par source — chaque source garde sa forme native sous sa propre clé (`{"openalex": [...], "scanr": ..., "theses": {...}}`).
- **`doc_type`** : premier non-null avec arbitrage des sous-types d'article (CrossRef renvoie `journal-article` indistinctement pour review / book_review / data_paper / etc. — si une source moins prioritaire propose un sous-type plus précis, on le préfère pour ne pas perdre l'information). Les valeurs lues sont déjà canoniques et corrigées (mapping + corrections persistés en amont sur la `source_publication`).

Priorité d'ordre : les enregistrements canoniques passent avant les formes secondaires convergées (`secondary_ids` — pièce, version ou variante dont le DOI a été substitué par celui de l'œuvre canonique), afin que les scalaires descriptifs (titre en tête) viennent de l'enregistrement qui porte nativement le DOI, pas d'une pièce. La priorité de source départage à l'intérieur de chaque groupe.

`title_normalized` est recalculé à partir du `title` agrégé, pas pris d'une source (les sources ne fournissent pas ce champ).
"""

from typing import cast

from domain.normalize import normalize_text
from domain.publications.doc_types import ARTICLE_SUBTYPES
from domain.publications.identifiers import DOI
from domain.publications.metadata import (
    OA_CLOSED_STATUSES,
    OA_STATUS_UNKNOWN_DEFAULT,
    best_oa_status,
    has_open_archive_deposit,
)
from domain.publications.publication import Publication
from domain.source_publications.source_publication import SourcePublication
from domain.types import JsonValue, as_int, as_str


def refresh_from_sources(
    pub: Publication,
    sources: list[SourcePublication],
    *,
    source_priority: tuple[str, ...],
    secondary_ids: frozenset[int] = frozenset(),
) -> None:
    """Recalcule l'état canonique de `pub` (DOI, oa_status, méta, etc.) par agrégation de ses `sources`. Mute `pub` en place ; persistance via `repo.save(pub)` côté caller.

    Règles d'agrégation : premier non-null par `source_priority` pour les scalaires nullable, statut OA le plus ouvert toutes sources confondues, union dédupliquée des listes, fusion shallow par clé des JSONB, `topics` indexés par source.

    `secondary_ids` liste les `source_publications` qui décrivent une **forme secondaire** de l'œuvre — une pièce, une version ou une variante dont le DOI a été substitué par le DOI de l'œuvre canonique (correction de convergence). Elles sont reléguées en fin de priorité, sous les enregistrements canoniques, pour que les scalaires descriptifs (titre en tête) proviennent de l'enregistrement qui porte nativement le DOI, et non d'une pièce prise au hasard (un `README.txt`, un fichier de données). Les listes restent unionnées toutes sources confondues : une pièce peut porter un mot-clé légitime.

    Précondition : `sources` non vide. Le cas orphelin (aucune source) est une décision métier qui doit être traitée par le caller avant d'appeler cette fonction (suppression de la publication via `repo.delete`).
    """
    if not sources:
        raise ValueError(
            "refresh_from_sources requiert au moins une source ; le cas orphelin est à traiter côté caller (suppression de la publication)"
        )

    rank = {s: i for i, s in enumerate(source_priority)}
    sorted_sources = sorted(sources, key=lambda s: (s.id in secondary_ids, rank.get(s.source, 99)))

    new_title = as_str(first_non_null(sorted_sources, "title"))
    pub.title = new_title if new_title is not None else pub.title
    pub.title_normalized = normalize_text(pub.title) if pub.title else None
    pub.doc_type = arbitrate_doc_type_with_article_subtype(sorted_sources)
    pub.pub_year = as_int(first_non_null(sorted_sources, "pub_year")) or pub.pub_year

    new_doi_str = as_str(first_non_null(sorted_sources, "doi"))
    pub.doi = DOI(new_doi_str) if new_doi_str else None

    pub.journal_id = as_int(first_non_null(sorted_sources, "journal_id"))
    # Unpaywall fait autorité sur l'OA une fois qu'il a été interrogé (cf.
    # `publications.unpaywall_checked_at`) : on ne ré-agrège `oa_status` depuis les
    # sources que tant que la publication ne l'a pas été. Sinon un réimport
    # écraserait le verdict d'Unpaywall par une valeur de source, jusqu'à la
    # prochaine péremption.
    if pub.unpaywall_checked_at is None:
        pub.oa_status = (
            best_oa_status(s.oa_status for s in sorted_sources) or OA_STATUS_UNKNOWN_DEFAULT
        )
    elif pub.oa_status in OA_CLOSED_STATUSES and has_open_archive_deposit(sorted_sources):
        # Plancher dépôt-archive : Unpaywall a refermé (`closed`/`unknown`) une publication dont
        # une archive ouverte détient le fichier (HAL `green`). Le fichier est un fait qu'Unpaywall
        # ne voit pas sous le DOI — on rouvre depuis les sources. Hors ce cas, Unpaywall garde son
        # autorité (il arbitre les prétentions d'ouverture sans dépôt).
        pub.oa_status = (
            best_oa_status(s.oa_status for s in sorted_sources) or OA_STATUS_UNKNOWN_DEFAULT
        )
    pub.container_title = as_str(first_non_null(sorted_sources, "container_title"))
    pub.language = as_str(first_non_null(sorted_sources, "language"))
    pub.abstract = as_str(first_non_null(sorted_sources, "abstract"))
    pub.keywords = _textes(merge_lists_dedup_ci(sorted_sources, "keywords"))
    pub.countries = _textes(merge_lists_dedup_ci(sorted_sources, "countries"))
    pub.topics = topics_by_source(sorted_sources)
    pub.biblio = shallow_merge_jsonb(sorted_sources, "biblio")
    pub.meta = shallow_merge_jsonb(sorted_sources, "meta")
    pub.is_retracted = any(s.is_retracted for s in sorted_sources if s.is_retracted)


# ── Helpers publics ────────────────────────────────────────────────


def _textes(valeurs: list[JsonValue] | None) -> tuple[str, ...]:
    """Valeurs textuelles d'une liste fusionnée : mots-clés et pays sont du texte, le reste ne s'écrit pas."""
    return tuple(texte for v in valeurs or () if (texte := as_str(v)))


def first_non_null(sources: list[SourcePublication], attr: str) -> JsonValue:
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


def merge_lists_dedup_ci(sources: list[SourcePublication], attr: str) -> list[JsonValue] | None:
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


def topics_by_source(
    sources: list[SourcePublication],
) -> dict[str, JsonValue] | None:
    """Indexe les `topics` par source. Schémas radicalement différents par source — chacun reste sous sa propre clé pour préserver la forme native (liste hiérarchique OpenAlex, dict ScanR, etc.)."""
    out: dict[str, JsonValue] = {}
    for s in sources:
        if s.topics:
            out[s.source] = s.topics
    return out or None


def arbitrate_doc_type_with_article_subtype(sources: list[SourcePublication]) -> str:
    """Choix du `doc_type` canonique : premier non-null dans l'ordre de priorité, avec exception pour les sous-types d'article.

    Les `doc_type` lus sont déjà **canoniques et corrigés** (la phase `metadata_correction` a mappé source→canonique et appliqué les corrections en place sur la `source_publication`) ; l'arbitrage opère directement sur les colonnes, sans re-mapper.

    CrossRef (priorité 2) renvoie `journal-article` indistinctement pour tous les sous-types (review, book_review, data_paper, poster, conference_paper, editorial, letter, erratum, retraction). Une source moins prioritaire ayant produit un de ces sous-types plus précis, on le préfère pour ne pas perdre l'information.
    """
    article_subtype_present: str | None = None
    for s in sources:
        if not s.doc_type:
            continue
        if s.doc_type in ARTICLE_SUBTYPES:
            article_subtype_present = s.doc_type
            break

    for s in sources:
        if not s.doc_type:
            continue
        if s.doc_type == "article" and article_subtype_present:
            return article_subtype_present
        return s.doc_type
    return "other"
