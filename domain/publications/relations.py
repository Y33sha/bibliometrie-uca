"""Relations entre publications distinctes : types, et traduction des vocabulaires de DataCite (`relationType`) et de Crossref (clés de `relation`).

Restent hors du vocabulaire, et donnent `None` :

- les formes d'une même œuvre (versions, formes identiques), que la phase `metadata_correction` fusionne ;
- les citations ;
- les évaluations et commentaires (`is-review-of`, `is-comment-on`) ;
- les dérivations vagues (`IsDerivedFrom`, `is-related-material`…).
"""

from __future__ import annotations

from enum import StrEnum

from domain.publications.identifiers import clean_doi
from domain.source_records.metadata_correction.shared_doi import (
    DATACITE_DIRECT_CONVERGENCE,
    meme_oeuvre_declaree,
)
from domain.source_records.source_extras import CROSSREF_PREPRINT_OF, SourceExtra
from domain.types import JsonValue, as_str


class RelationType(StrEnum):
    """Type orienté de relation : `<sujet> <type> <objet>`. Chaque type a son inverse : la relation s'enregistre depuis la publication qui la déclare, l'autre pouvant être hors corpus."""

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
    # Data paper → jeu de données décrit. Un article qui décrit un jeu de données est un data paper.
    DESCRIBES = "describes"
    IS_DESCRIBED_BY = "is_described_by"
    # Symétrique : deux publications distinctes partagent une clé de confirmation, et leurs types de document ne précisent pas la relation.
    IS_RELATED_TO = "is_related_to"


RELATION_PAIR_LABELS: dict[RelationType, str] = {
    RelationType.IS_PREPRINT_OF: "préprint/article",
    RelationType.HAS_PREPRINT: "préprint/article",
    RelationType.IS_CORRECTION_OF: "article/erratum",
    RelationType.HAS_CORRECTION: "article/erratum",
    RelationType.IS_RETRACTION_OF: "article/rétractation",
    RelationType.HAS_RETRACTION: "article/rétractation",
    RelationType.IS_CONCERN_ABOUT: "article/avis de préoccupation",
    RelationType.HAS_CONCERN: "article/avis de préoccupation",
    RelationType.IS_SUPPLEMENT_TO: "article/données supplémentaires",
    RelationType.HAS_SUPPLEMENT: "article/données supplémentaires",
    RelationType.IS_PART_OF: "partie/ensemble",
    RelationType.HAS_PART: "partie/ensemble",
    RelationType.IS_TRANSLATION_OF: "traduction/original",
    RelationType.HAS_TRANSLATION: "traduction/original",
    RelationType.DESCRIBES: "data paper/jeu de données",
    RelationType.IS_DESCRIBED_BY: "data paper/jeu de données",
    RelationType.IS_RELATED_TO: "apparentées, type à qualifier",
}
"""Libellé commun à un type et à son inverse."""


# Types DataCite du vocabulaire.
_DATACITE_MAP: dict[str, RelationType] = {
    "IsSupplementTo": RelationType.IS_SUPPLEMENT_TO,
    "IsSupplementedBy": RelationType.HAS_SUPPLEMENT,
    # Partie d'un ensemble (chapitre d'un ouvrage, communication d'actes). La phase `metadata_correction` fusionne les fichiers d'un même dépôt de données.
    "IsPartOf": RelationType.IS_PART_OF,
    "HasPart": RelationType.HAS_PART,
    "Describes": RelationType.DESCRIBES,
    "IsDescribedBy": RelationType.IS_DESCRIBED_BY,
    "IsDocumentedBy": RelationType.IS_DESCRIBED_BY,
}

# Clés Crossref du vocabulaire.
_CROSSREF_MAP: dict[str, RelationType] = {
    CROSSREF_PREPRINT_OF: RelationType.IS_PREPRINT_OF,
    "has-preprint": RelationType.HAS_PREPRINT,
    "is-supplement-to": RelationType.IS_SUPPLEMENT_TO,
    "is-supplemented-by": RelationType.HAS_SUPPLEMENT,
    # Correction : l'article déclare la clé, vers son erratum.
    "erratum": RelationType.HAS_CORRECTION,
    "correction": RelationType.HAS_CORRECTION,
    "corrigendum": RelationType.HAS_CORRECTION,
    "addendum": RelationType.HAS_CORRECTION,
    "clarification": RelationType.HAS_CORRECTION,
    "corrected": RelationType.IS_CORRECTION_OF,
    # Rétractation : l'article déclare la clé, vers l'avis de rétractation ou de retrait.
    "retraction": RelationType.HAS_RETRACTION,
    "withdrawal": RelationType.HAS_RETRACTION,
    # Avis de préoccupation de l'éditeur : l'article déclare la clé, vers l'avis.
    "expression_of_concern": RelationType.HAS_CONCERN,
    "is-translation-of": RelationType.IS_TRANSLATION_OF,
    "has-translation": RelationType.HAS_TRANSLATION,
    # Data paper → jeu de données : Crossref l'exprime par `is-part-of` (data papers de Copernicus).
    "is-part-of": RelationType.DESCRIBES,
    "has-part": RelationType.IS_DESCRIBED_BY,
}


# Paires inverses : sur la page de B, `A is_preprint_of B` se lit `B has_preprint A`.
_INVERSE_PAIRS: tuple[tuple[RelationType, RelationType], ...] = (
    (RelationType.IS_PREPRINT_OF, RelationType.HAS_PREPRINT),
    (RelationType.IS_SUPPLEMENT_TO, RelationType.HAS_SUPPLEMENT),
    (RelationType.IS_PART_OF, RelationType.HAS_PART),
    (RelationType.IS_CORRECTION_OF, RelationType.HAS_CORRECTION),
    (RelationType.IS_RETRACTION_OF, RelationType.HAS_RETRACTION),
    (RelationType.IS_CONCERN_ABOUT, RelationType.HAS_CONCERN),
    (RelationType.IS_TRANSLATION_OF, RelationType.HAS_TRANSLATION),
    (RelationType.DESCRIBES, RelationType.IS_DESCRIBED_BY),
)
_INVERSE_RELATIONS: dict[RelationType, RelationType] = {
    RelationType.IS_RELATED_TO: RelationType.IS_RELATED_TO,
    # Les deux sens s'écrivent en parallèle, ce qui se lit mieux que `dict(_INVERSE_PAIRS)`.
    **{a: b for a, b in _INVERSE_PAIRS},  # noqa: C416
    **{b: a for a, b in _INVERSE_PAIRS},
}


def inverse_relation(relation: RelationType) -> RelationType:
    """Type inverse (la relation vue depuis l'autre bout). `is_related_to`, symétrique, est son propre inverse."""
    return _INVERSE_RELATIONS[relation]


def map_datacite_relation(relation_type: str) -> RelationType | None:
    """Type d'un `relationType` DataCite, ou `None`."""
    return _DATACITE_MAP.get(relation_type)


def map_crossref_relation(relation_key: str) -> RelationType | None:
    """Type d'une clé de `relation` Crossref, ou `None`."""
    return _CROSSREF_MAP.get(relation_key)


def extract_datacite_relations(
    source_extras: dict[str, JsonValue] | None,
) -> list[tuple[RelationType, str]]:
    """Relations du vocabulaire déclarées par un enregistrement source DataCite : `(type, DOI cible)`. Les entrées sans DOI sont ignorées."""
    related = (source_extras or {}).get(SourceExtra.RELATED_IDENTIFIERS)
    if not isinstance(related, list):
        return []
    out: list[tuple[RelationType, str]] = []
    for item in related:
        if not isinstance(item, dict):
            continue
        canonical = map_datacite_relation(as_str(item.get("relation_type")) or "")
        target = clean_doi(as_str(item.get("doi")))
        if canonical and target:
            out.append((canonical, target))
    return out


def extract_datacite_distinct_works(
    source_extras: dict[str, JsonValue] | None, own_doi: str | None, doc_type: str | None
) -> list[str]:
    """DOI qu'un enregistrement source DataCite déclare comme autre forme de son œuvre, quand la relation relie deux œuvres.

    `own_doi` et `doc_type` sont ceux de l'enregistrement source déclarant, que lit `meme_oeuvre_declaree`.
    """
    related = (source_extras or {}).get(SourceExtra.RELATED_IDENTIFIERS)
    if not isinstance(related, list):
        return []
    out: list[str] = []
    for item in related:
        if not isinstance(item, dict):
            continue
        case = DATACITE_DIRECT_CONVERGENCE.get(as_str(item.get("relation_type")) or "")
        if case is None:
            continue
        target = clean_doi(as_str(item.get("doi")))
        if target and not meme_oeuvre_declaree(case, doc_type, own_doi, target):
            out.append(target)
    return out


# Types de document dépendants, sujets d'une relation vers l'œuvre principale : preprint, erratum, jeu de données.
# Ils typent la relation de deux publications qui partagent une clé (`infer_shared_key_relation`) ou un titre (phase `relations`).
DEPENDENT_DOC_TYPE_RELATIONS: dict[str, RelationType] = {
    "preprint": RelationType.IS_PREPRINT_OF,
    "erratum": RelationType.IS_CORRECTION_OF,
    "dataset": RelationType.IS_SUPPLEMENT_TO,
}


def infer_shared_key_relation(
    doc_type_a: str | None, doc_type_b: str | None
) -> tuple[RelationType, str] | None:
    """Relation de deux publications distinctes qui partagent une clé de confirmation, d'après leurs types de document : `(type, sujet)`, le sujet valant `"a"`, `"b"`, ou `"sym"` pour `is_related_to`. `None` pour une évaluation par les pairs.

    Un preprint, un erratum, un jeu de données, ou un chapitre face à son ouvrage, donnent une relation orientée. Les autres couples donnent `is_related_to`.
    """
    if "peer_review" in (doc_type_a, doc_type_b):
        return None
    for dependent, relation in DEPENDENT_DOC_TYPE_RELATIONS.items():
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


def extract_crossref_relations(
    source_extras: dict[str, JsonValue] | None,
) -> list[tuple[RelationType, str]]:
    """Relations du vocabulaire déclarées par un enregistrement source Crossref : `(type, DOI cible)`. Seules comptent les cibles de type DOI."""
    relation = (source_extras or {}).get(SourceExtra.RELATION)
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
            target = clean_doi(as_str(entry.get("id")))
            if target:
                out.append((canonical, target))
    return out
