"""Relations entre publications distinctes : types, et traduction des vocabulaires de DataCite (`relationType`) et de Crossref (clés de `relation`).

Restent hors du vocabulaire, et donnent `None` :

- les formes d'une même œuvre (versions, formes identiques), que la phase `metadata_correction` fusionne ;
- les citations ;
- les évaluations et commentaires (`is-review-of`, `is-comment-on`) ;
- les dérivations vagues (`IsDerivedFrom`, `is-related-material`…).
"""

from collections.abc import Iterator
from enum import StrEnum

from domain.documents.doc_types import DocType
from domain.documents.identifiers import DOI
from domain.source_records.metadata_correction.shared_doi import (
    DATACITE_DIRECT_CONVERGENCE,
    declares_same_work,
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
    DESCRIBES = "describes"
    """Data paper → jeu de données décrit. Un article qui décrit un jeu de données est un data paper."""
    IS_DESCRIBED_BY = "is_described_by"
    IS_RELATED_TO = "is_related_to"
    """Relation symétrique : deux publications distinctes partagent une clé de confirmation, et leurs types de document ne précisent pas la relation."""


_PAIRS: tuple[tuple[RelationType, RelationType, str], ...] = (
    (RelationType.IS_PREPRINT_OF, RelationType.HAS_PREPRINT, "préprint/article"),
    (RelationType.IS_SUPPLEMENT_TO, RelationType.HAS_SUPPLEMENT, "article/données supplémentaires"),
    (RelationType.IS_PART_OF, RelationType.HAS_PART, "partie/ensemble"),
    (RelationType.IS_CORRECTION_OF, RelationType.HAS_CORRECTION, "article/erratum"),
    (RelationType.IS_RETRACTION_OF, RelationType.HAS_RETRACTION, "article/rétractation"),
    (RelationType.IS_CONCERN_ABOUT, RelationType.HAS_CONCERN, "article/avis de préoccupation"),
    (RelationType.IS_TRANSLATION_OF, RelationType.HAS_TRANSLATION, "traduction/original"),
    (RelationType.DESCRIBES, RelationType.IS_DESCRIBED_BY, "data paper/jeu de données"),
)
"""Paires de types inverses, avec leur libellé commun : sur la page de B, `A is_preprint_of B` se lit `B has_preprint A`."""

RELATION_PAIR_LABELS: dict[RelationType, str] = {
    **{relation: label for a, b, label in _PAIRS for relation in (a, b)},
    RelationType.IS_RELATED_TO: "apparentées, type à qualifier",
}
"""Libellé commun à un type et à son inverse."""


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
"""Types DataCite du vocabulaire."""

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
"""Clés Crossref du vocabulaire."""


_INVERSE_RELATIONS: dict[RelationType, RelationType] = {
    RelationType.IS_RELATED_TO: RelationType.IS_RELATED_TO,
    **{a: b for a, b, _ in _PAIRS},
    **{b: a for a, b, _ in _PAIRS},
}


def inverse_relation(relation: RelationType) -> RelationType:
    """Renvoie le type inverse (la relation vue depuis l'autre bout). `is_related_to`, symétrique, est son propre inverse."""
    return _INVERSE_RELATIONS[relation]


def _datacite_related(source_extras: dict[str, JsonValue] | None) -> Iterator[tuple[str, str]]:
    """Renvoie les relations déclarées par un enregistrement source DataCite : `(relationType, DOI cible)`, DOI normalisé à l'ingestion. Les entrées sans DOI sont ignorées."""
    related = (source_extras or {}).get(SourceExtra.RELATED_IDENTIFIERS)
    if not isinstance(related, list):
        return
    for item in related:
        if isinstance(item, dict) and (target := as_str(item.get("doi"))):
            yield as_str(item.get("relation_type")) or "", target


def extract_datacite_relations(
    source_extras: dict[str, JsonValue] | None,
) -> list[tuple[RelationType, str]]:
    """Renvoie les relations du vocabulaire déclarées par un enregistrement source DataCite : `(type, DOI cible)`."""
    return [
        (relation, target)
        for relation_type, target in _datacite_related(source_extras)
        if (relation := _DATACITE_MAP.get(relation_type))
    ]


def extract_datacite_distinct_works(
    source_extras: dict[str, JsonValue] | None, own_doi: str | None, doc_type: str | None
) -> list[str]:
    """Renvoie les DOI déclarés par un enregistrement source DataCite comme autre forme de son œuvre, quand la relation relie deux œuvres.

    `own_doi` et `doc_type` sont ceux de l'enregistrement source déclarant, lus par `declares_same_work`.
    """
    return [
        target
        for relation_type, target in _datacite_related(source_extras)
        if (case := DATACITE_DIRECT_CONVERGENCE.get(relation_type)) is not None
        and not declares_same_work(case, doc_type, own_doi, target)
    ]


DEPENDENT_DOC_TYPE_RELATIONS: dict[str, RelationType] = {
    DocType.PREPRINT: RelationType.IS_PREPRINT_OF,
    DocType.ERRATUM: RelationType.IS_CORRECTION_OF,
    DocType.DATASET: RelationType.IS_SUPPLEMENT_TO,
}
"""Types de document dépendants, sujets d'une relation vers l'œuvre principale : preprint, erratum, jeu de données. Ils typent la relation de deux publications qui partagent une clé (`infer_shared_key_relation`) ou un titre (phase `relations`)."""


def infer_shared_key_relation(
    doc_type_a: str | None, doc_type_b: str | None
) -> tuple[RelationType, bool] | None:
    """Déduit la relation de deux publications distinctes qui partagent une clé de confirmation, d'après leurs types de document : `(type, le sujet est b)`. Sans sujet désigné, A est le sujet. `None` pour une évaluation par les pairs.

    Un preprint, un erratum, un jeu de données, ou un chapitre face à son ouvrage, donnent une relation orientée. Les autres couples donnent `is_related_to`.
    """
    if DocType.PEER_REVIEW in (doc_type_a, doc_type_b):
        return None
    for dependent, relation in DEPENDENT_DOC_TYPE_RELATIONS.items():
        a_is_dependent = doc_type_a == dependent
        b_is_dependent = doc_type_b == dependent
        if a_is_dependent and not b_is_dependent:
            return relation, False
        if b_is_dependent and not a_is_dependent:
            return relation, True
    if {doc_type_a, doc_type_b} == {DocType.BOOK, DocType.BOOK_CHAPTER}:
        # Le chapitre est partie de l'ouvrage.
        return RelationType.IS_PART_OF, doc_type_b == DocType.BOOK_CHAPTER
    return RelationType.IS_RELATED_TO, False


def extract_crossref_relations(
    source_extras: dict[str, JsonValue] | None,
) -> list[tuple[RelationType, str]]:
    """Renvoie les relations du vocabulaire déclarées par un enregistrement source Crossref : `(type, DOI cible)`. Seules comptent les cibles de type DOI."""
    relation = (source_extras or {}).get(SourceExtra.RELATION)
    if not isinstance(relation, dict):
        return []
    out: list[tuple[RelationType, str]] = []
    for key, entries in relation.items():
        canonical = _CROSSREF_MAP.get(key)
        if not canonical or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id-type") != "doi":
                continue
            target = DOI.normalize(as_str(entry.get("id")))
            if target:
                out.append((canonical, target))
    return out
