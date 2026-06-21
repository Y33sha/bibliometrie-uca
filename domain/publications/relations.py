"""Vocabulaire canonique des relations entre publications + mapping des sources.

Les relations modélisées ici lient des publications **distinctes** (pas des doublons). Deux sources déclarent des relations, avec des vocabulaires différents :

- **DataCite** : `relatedIdentifiers[].relationType` (`IsSupplementTo`, `IsPartOf`…), stocké dans `source_publications.meta.related_identifiers`.
- **Crossref** : clés de `meta.relation` (`is-preprint-of`, `erratum`…), stocké dans `source_publications.meta.relation`.

Ce module fige un jeu de **types canoniques** (directionnels) et le mapping de chaque vocabulaire source vers ce jeu. Les types hors scope renvoient `None`.

Hors scope (renvoient `None`), avec leur raison :

- **Même œuvre** (versions, formes identiques) : `IsVersionOf` / `HasVersion` / `IsIdenticalTo` / `IsNewVersionOf` / `IsVariantFormOf` / `IsOriginalFormOf` côté DataCite ; `is-version-of` / `has-version` / `new_version` / `is-identical-to` / `is-same-as` côté Crossref. → déduplication (phase `metadata_correction`), pas une relation.
- **Citations** : `References` / `Cites` / `IsCitedBy` / `IsReferencedBy` ; `references` / `is-referenced-by` / `is-cited-by`. → graphe bibliographique.
- **Peer-review** : `has-review` / `is-review-of` (Crossref), `IsReviewedBy` (DataCite). → évaluation, pas une œuvre apparentée.
- **Vague / dérivation** : `IsDerivedFrom`, `IsSourceOf`, `Requires`, `Continues`, `IsPublishedIn` ; `has-manifestation`, `is-related-material`, `has-related-material`, `is-basis-for`.

Directionnalité : chaque relation est stockée depuis la publication qui la **déclare** (toujours en corpus), avec un type qui porte le sens. Les paires inverses (ex. `IsSupplementTo` / `IsSupplementedBy`) mappent vers des types canoniques inverses. La déduplication des arêtes inverses (quand les deux bouts sont en corpus et déclarent tous deux) relève de la phase de population.
"""

from __future__ import annotations

from enum import StrEnum


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
    IS_TRANSLATION_OF = "is_translation_of"
    HAS_TRANSLATION = "has_translation"
    # Data paper ↔ jeu de données décrit. Sert aussi à détecter et retyper les
    # data papers (un article qui `describes` un dataset en est un).
    DESCRIBES = "describes"
    IS_DESCRIBED_BY = "is_described_by"


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
    "is-translation-of": RelationType.IS_TRANSLATION_OF,
    "has-translation": RelationType.HAS_TRANSLATION,
    # Data paper ↔ dataset décrit. Crossref l'exprime via `is-part-of` (data paper
    # Copernicus → dataset). Cible attendue = un dataset (à confirmer par audit).
    "is-part-of": RelationType.DESCRIBES,
    "has-part": RelationType.IS_DESCRIBED_BY,
}

# À trancher avant d'inclure, après audit de la nature des entités liées :
# - Crossref `is-comment-on` / `has-comment` : peut recouvrir du peer-review ou de
#   la discussion — nature à auditer.
# - Crossref `expression_of_concern` : ni correction ni rétractation franche.
# - DataCite `IsVariantFormOf` : même œuvre sous une autre forme → déduplication
#   ou relation ?


def map_datacite_relation(relation_type: str) -> RelationType | None:
    """Type canonique d'un `relationType` DataCite, ou `None` si hors scope."""
    return _DATACITE_MAP.get(relation_type)


def map_crossref_relation(relation_key: str) -> RelationType | None:
    """Type canonique d'une clé `meta.relation` Crossref, ou `None` si hors scope."""
    return _CROSSREF_MAP.get(relation_key)
