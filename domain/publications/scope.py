"""Périmètre des publications : types de document admissibles, enregistrements sources écartés."""

from collections.abc import Sequence, Set
from typing import NamedTuple

from domain.publications.metadata import normalized_title
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    active,
    own_dois,
)
from domain.source_records.keys import CONFIRMATION_ID_TYPES
from domain.sources.registry import AGGREGATOR_SOURCES, Source
from domain.sources.scanr import extract_hal_id_from_scanr_id

OUT_OF_SCOPE_DOC_TYPES = frozenset({"peer_review", "practice_thesis", "memoir", "physical_object"})
"""Types de document exclus des publications. Une œuvre de l'un de ces types reste sans publication. Ses enregistrements sources et ses contributions sources restent en base, sans contribution ni personne.

- `peer_review` : rapport d'évaluation d'un article.
- `practice_thesis`, `memoir` : thèse d'exercice et mémoire d'étudiant, surtout de DUMAS ; leurs auteurs sont de passage.
- `physical_object` : échantillon ou instrument identifié par un DOI DataCite (IGSN).
"""

EXCLUDED_DOI_PREFIXES = frozenset({"10.60692"})
"""Préfixes DOI dont les enregistrements sources sont écartés de la réconciliation.

- `10.60692` : GRESIS (gresis.osc.int). Copies d'enregistrements OpenAlex aux titres traduits automatiquement, sans relation déclarée avec le DOI de l'éditeur.
"""

PARATEXT_TITLES = frozenset(
    normalized_title(title)
    for title in (
        "Auteurs",
        "Bibliographie",
        "Bibliographie sélective",
        "Contributors",
        "Front Matter",
        "Frontmatter",
        "Index",
        "Index des notions",
        "Index des personnes",
        "Les auteurs",
        "List of Authors",
        "List of Contributors",
        "Liste des auteurs",
        "Notes on Contributors",
        "README.txt",
        "References",
        "Sommaire",
        "Table des matières",
        "Table of Contents",
    )
)
"""Titres normalisés de paratexte : pages liminaires, listes d'auteurs, index, bibliographies. Leurs enregistrements sources sont écartés de la réconciliation."""


class MatchabilityFacts(NamedTuple):
    """Faits d'un enregistrement source que lit `is_matchable`.

    `urls` : URL de copie, privées des dépôts HAL introuvables. `identifiers` : identifiants de l'enregistrement source, avec leur statut. `primary_doi_target_recorded` : son DOI `primary` a une cible dans `doi_targets`, et cette cible est le DOI `primary` d'un autre enregistrement source.
    """

    source: str
    source_id: str
    title_normalized: str | None
    urls: Sequence[str]
    identifiers: Sequence[SourceIdentifier]
    primary_doi_target_recorded: bool = False


def is_matchable(facts: MatchabilityFacts, missing_hal_ids: Set[str]) -> bool:
    """Vrai si l'enregistrement source entre dans la réconciliation. Il en est écarté si :

    - tous ses DOI propres (`own_dois`), quel que soit leur statut, ont un préfixe de `EXCLUDED_DOI_PREFIXES` ;
    - il vient de DataCite et la cible de son DOI `primary` est le DOI `primary` d'un autre enregistrement source : il est une forme secondaire d'une œuvre que cet enregistrement source représente ;
    - son titre normalisé est dans `PARATEXT_TITLES` ;
    - il vient de ScanR et il est issu d'un dépôt HAL de `missing_hal_ids` ;
    - il vient d'une source de `AGGREGATOR_SOURCES` et il n'a aucun DOI actif de rôle autre que `related`, aucune URL de copie et aucune clé de confirmation active.
    """
    own = own_dois(facts.identifiers)
    if own and all(doi.split("/", 1)[0] in EXCLUDED_DOI_PREFIXES for doi in own):
        return False
    if facts.source == Source.DATACITE and facts.primary_doi_target_recorded:
        return False
    if facts.title_normalized in PARATEXT_TITLES:
        return False
    if facts.source == Source.SCANR and (
        extract_hal_id_from_scanr_id(facts.source_id) in missing_hal_ids
    ):
        return False
    if facts.source in AGGREGATOR_SOURCES:
        return bool(facts.urls) or any(
            i.id_type in CONFIRMATION_ID_TYPES
            or (
                i.id_type is SourceIdentifierType.DOI and i.role is not SourceIdentifierRole.RELATED
            )
            for i in active(facts.identifiers)
        )
    return True
