"""Vocabulaire canonique des relations entre publications + mapping des sources.

Les relations modélisées ici lient des publications **distinctes** (pas des doublons). Deux sources déclarent des relations, avec des vocabulaires différents :

- **DataCite** : `relatedIdentifiers[].relationType` (`IsSupplementTo`, `IsPartOf`…), stocké dans `source_publications.meta.related_identifiers`.
- **Crossref** : clés de `meta.relation` (`is-preprint-of`, `erratum`…), stocké dans `source_publications.meta.relation`.

Ce module fige un jeu de **types canoniques** (directionnels) et le mapping de chaque vocabulaire source vers ce jeu. Les types hors scope renvoient `None`.

Hors scope (renvoient `None`), avec leur raison :

- **Même œuvre** (versions, formes identiques) : `IsVersionOf` / `HasVersion` / `IsIdenticalTo` / `IsNewVersionOf` / `IsVariantFormOf` / `IsOriginalFormOf` côté DataCite ; `is-version-of` / `has-version` / `new_version` / `is-identical-to` / `is-same-as` côté Crossref. → déduplication (phase `metadata_correction`), pas une relation.
- **Citations** : `References` / `Cites` / `IsCitedBy` / `IsReferencedBy` ; `references` / `is-referenced-by` / `is-cited-by`. → graphe bibliographique.
- **Peer-review / discussion** : `has-review` / `is-review-of` / `is-comment-on` / `has-comment` (Crossref), `IsReviewedBy` (DataCite). → évaluation ou commentaire (le porteur de `is-comment-on` est un `peer_review`), pas une œuvre apparentée.
- **Vague / dérivation** : `IsDerivedFrom`, `IsSourceOf`, `Requires`, `Continues`, `IsPublishedIn` ; `has-manifestation`, `is-related-material`, `has-related-material`, `is-basis-for`.

Directionnalité : chaque relation est stockée depuis la publication qui la **déclare** (toujours en corpus), avec un type qui porte le sens. Les paires inverses (ex. `IsSupplementTo` / `IsSupplementedBy`) mappent vers des types canoniques inverses. La déduplication des arêtes inverses (quand les deux bouts sont en corpus et déclarent tous deux) relève de la phase de population.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from domain.publications.identifiers import clean_doi


class RelationType(StrEnum):
    """Types canoniques de relation entre publications distinctes (directionnels).

    Convention : `<sujet> <type> <objet>`, le sujet étant la publication porteuse. Chaque type a son inverse pour pouvoir stocker la relation depuis le bout qui la déclare (l'autre bout pouvant être hors corpus).
    """

    IS_PREPRINT_OF = "is_preprint_of"
    HAS_PREPRINT = "has_preprint"
    IS_SUPPLEMENT_TO = "is_supplement_to"
    HAS_SUPPLEMENT = "has_supplement"
    IS_PART_OF = "is_part_of"
    HAS_PART = "has_part"
    IS_CORRECTION_OF = "is_correction_of"
    HAS_CORRECTION = "has_correction"
    IS_RETRACTION_OF = "is_retraction_of"
    HAS_RETRACTION = "has_retraction"
    IS_CONCERN_ABOUT = "is_concern_about"
    HAS_CONCERN = "has_concern"
    IS_TRANSLATION_OF = "is_translation_of"
    HAS_TRANSLATION = "has_translation"
    # Data paper ↔ jeu de données décrit. Sert aussi à détecter et retyper les
    # data papers (un article qui `describes` un dataset en est un).
    DESCRIBES = "describes"
    IS_DESCRIBED_BY = "is_described_by"
    # Apparentée, type à qualifier : deux publications distinctes partagent une clé de confirmation
    # (DOI distincts) mais leur couple de doc_type ne permet pas (encore) d'inférer une relation
    # précise. Symétrique (non directionnel), bucket d'attente du signal #2.
    IS_RELATED_TO = "is_related_to"


# Mapping DataCite `relationType` → type canonique. Les types absents (citations,
# même-œuvre, vague — cf. docstring) sont hors scope et renvoient `None`.
_DATACITE_MAP: dict[str, RelationType] = {
    "IsSupplementTo": RelationType.IS_SUPPLEMENT_TO,
    "IsSupplementedBy": RelationType.HAS_SUPPLEMENT,
    # Partie structurelle (ouvrage ↔ chapitre, actes ↔ communication). Les pièces
    # intra-package (sous-fichiers d'un même dépôt de données) sont collapsées en
    # déduplication en amont (`metadata_correction`), donc absentes ici en régime.
    "IsPartOf": RelationType.IS_PART_OF,
    "HasPart": RelationType.HAS_PART,
    # Data paper ↔ dataset décrit.
    "Describes": RelationType.DESCRIBES,
    "IsDescribedBy": RelationType.IS_DESCRIBED_BY,
    "IsDocumentedBy": RelationType.IS_DESCRIBED_BY,
}

# Mapping Crossref (clés de `meta.relation`) → type canonique.
_CROSSREF_MAP: dict[str, RelationType] = {
    "is-preprint-of": RelationType.IS_PREPRINT_OF,
    "has-preprint": RelationType.HAS_PREPRINT,
    "is-supplement-to": RelationType.IS_SUPPLEMENT_TO,
    "is-supplemented-by": RelationType.HAS_SUPPLEMENT,
    # Famille correction : la clé est portée par l'article, pointant vers sa notice
    # (erratum/corrigendum/addendum). Sens : l'article « a une correction ».
    "erratum": RelationType.HAS_CORRECTION,
    "correction": RelationType.HAS_CORRECTION,
    "corrigendum": RelationType.HAS_CORRECTION,
    "addendum": RelationType.HAS_CORRECTION,
    "clarification": RelationType.HAS_CORRECTION,
    "corrected": RelationType.IS_CORRECTION_OF,
    # Rétractation : l'article pointe vers sa notice de rétractation/retrait.
    "retraction": RelationType.HAS_RETRACTION,
    "withdrawal": RelationType.HAS_RETRACTION,
    # Expression of concern : avis éditorial de doute post-publication (un cran sous
    # la rétractation), porté par l'article vers la notice.
    "expression_of_concern": RelationType.HAS_CONCERN,
    "is-translation-of": RelationType.IS_TRANSLATION_OF,
    "has-translation": RelationType.HAS_TRANSLATION,
    # Data paper ↔ dataset décrit. Crossref l'exprime via `is-part-of` (data paper
    # Copernicus → dataset). Cible attendue = un dataset (à confirmer par audit).
    "is-part-of": RelationType.DESCRIBES,
    "has-part": RelationType.IS_DESCRIBED_BY,
}


def map_datacite_relation(relation_type: str) -> RelationType | None:
    """Type canonique d'un `relationType` DataCite, ou `None` si hors scope."""
    return _DATACITE_MAP.get(relation_type)


def map_crossref_relation(relation_key: str) -> RelationType | None:
    """Type canonique d'une clé `meta.relation` Crossref, ou `None` si hors scope."""
    return _CROSSREF_MAP.get(relation_key)


def extract_datacite_relations(meta: dict[str, Any] | None) -> list[tuple[RelationType, str]]:
    """Relations en scope déclarées par un payload DataCite, depuis
    `meta.related_identifiers` (`[{doi, relation_type}]`). Renvoie `(type canonique,
    DOI cible)` ; ignore les types hors scope et les entrées sans DOI."""
    out: list[tuple[RelationType, str]] = []
    for item in (meta or {}).get("related_identifiers") or []:
        if not isinstance(item, dict):
            continue
        canonical = map_datacite_relation(item.get("relation_type") or "")
        target = clean_doi(item.get("doi"))
        if canonical and target:
            out.append((canonical, target))
    return out


# Signal #2 — inférence depuis le couple de doc_type d'une paire de publications distinctes (DOI
# distincts) partageant une clé de confirmation. Types « dépendants » : une publication de ce type
# est, par nature, sujet d'une relation dirigée vers l'œuvre principale (le preprint est_preprint_de
# l'article publié, l'erratum corrige l'article, le dataset complète l'article).
_DEPENDENT_SHARED_KEY_RELATIONS: tuple[tuple[str, RelationType], ...] = (
    ("preprint", RelationType.IS_PREPRINT_OF),
    ("erratum", RelationType.IS_CORRECTION_OF),
    ("dataset", RelationType.IS_SUPPLEMENT_TO),
)


def infer_shared_key_relation(
    doc_type_a: str | None, doc_type_b: str | None
) -> tuple[RelationType, str] | None:
    """Infère la relation entre deux publications **distinctes** (DOI distincts) qui partagent une
    clé de confirmation, depuis leur couple de `doc_type`.

    Renvoie `(type, sujet)` où `sujet` désigne le bout porteur de la relation dirigée : `"a"`
    (sujet = A), `"b"` (sujet = B), ou `"sym"` pour `is_related_to` (symétrique — le caller oriente
    par convention). Renvoie `None` si la paire est hors scope (peer-review).

    Un couple typé (preprint, erratum, dataset, ou ouvrage ↔ chapitre) donne une relation précise et
    dirigée ; tout autre couple — y compris deux exemplaires d'une même œuvre à DOI distincts non
    encore fusionnés — donne `is_related_to`, en attendant d'être qualifié."""
    if "peer_review" in (doc_type_a, doc_type_b):
        return None
    for dependent, relation in _DEPENDENT_SHARED_KEY_RELATIONS:
        a_is_dependent = doc_type_a == dependent
        b_is_dependent = doc_type_b == dependent
        if a_is_dependent and not b_is_dependent:
            return relation, "a"
        if b_is_dependent and not a_is_dependent:
            return relation, "b"
    if {doc_type_a, doc_type_b} == {"book", "book_chapter"}:
        # Le chapitre est partie de l'ouvrage.
        return RelationType.IS_PART_OF, ("a" if doc_type_a == "book_chapter" else "b")
    return RelationType.IS_RELATED_TO, "sym"


def extract_crossref_relations(meta: dict[str, Any] | None) -> list[tuple[RelationType, str]]:
    """Relations en scope déclarées par un payload Crossref, depuis `meta.relation`
    (`{clé: [{id, id-type, …}]}`). Renvoie `(type canonique, DOI cible)` ; ne garde que les
    cibles de type DOI et les clés en scope."""
    relation = (meta or {}).get("relation")
    if not isinstance(relation, dict):
        return []
    out: list[tuple[RelationType, str]] = []
    for key, entries in relation.items():
        canonical = map_crossref_relation(key)
        if not canonical or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id-type") != "doi":
                continue
            target = clean_doi(entry.get("id"))
            if target:
                out.append((canonical, target))
    return out
