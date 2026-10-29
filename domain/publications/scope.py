"""Périmètre des publications : types de document admissibles, enregistrements sources écartés."""

from collections.abc import Sequence, Set
from typing import NamedTuple

from domain.publications.metadata import normalized_title
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    active,
)
from domain.source_records.keys import CONFIRMATION_ID_TYPES
from domain.sources.registry import AGGREGATOR_SOURCES, Source
from domain.sources.scanr import extract_hal_id_from_scanr_id

OUT_OF_SCOPE_DOC_TYPES = frozenset({"peer_review", "memoir", "physical_object"})
"""Types de document exclus des publications. Une œuvre de l'un de ces types reste sans publication. Ses enregistrements sources et ses contributions sources restent en base, sans contribution ni personne.

- `peer_review` : rapport d'évaluation d'un article.
- `memoir` : mémoire d'étudiant, surtout de DUMAS ; ses auteurs sont de passage.
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

    `urls` : URL de copie, privées des dépôts HAL introuvables. `identifiers` : identifiants de l'enregistrement source, avec leur statut. `primary_doi_has_target` : son DOI `primary` est celui d'une forme secondaire, qui a une cible dans `doi_targets`.
    """

    source: str
    source_id: str
    title_normalized: str | None
    urls: Sequence[str]
    identifiers: Sequence[SourceIdentifier]
    primary_doi_has_target: bool = False


def _own_dois(identifiers: Sequence[SourceIdentifier]) -> set[str]:
    """DOI propres d'un enregistrement source, quel que soit leur statut : ses DOI `primary` ou `derived`, à défaut ses DOI `secondary`."""
    dois = [
        i
        for i in identifiers
        if i.id_type is SourceIdentifierType.DOI and i.role is not SourceIdentifierRole.RELATED
    ]
    strong = {
        i.value
        for i in dois
        if i.role in (SourceIdentifierRole.PRIMARY, SourceIdentifierRole.DERIVED)
    }
    return strong or {i.value for i in dois}


def is_matchable(facts: MatchabilityFacts, missing_hal_ids: Set[str]) -> bool:
    """Vrai si l'enregistrement source entre dans la réconciliation. Il en est écarté si :

    - tous ses DOI propres (`_own_dois`) ont un préfixe de `EXCLUDED_DOI_PREFIXES` ;
    - il vient de DataCite et son DOI `primary` a une cible : l'enregistrement source est une forme secondaire d'une œuvre présente en base ;
    - son titre normalisé est dans `PARATEXT_TITLES` ;
    - il vient de ScanR et il est issu d'un dépôt HAL de `missing_hal_ids` ;
    - il vient d'une source de `AGGREGATOR_SOURCES` et il n'a aucun DOI actif de rôle autre que `related`, aucune URL de copie et aucune clé de confirmation active.
    """
    own = _own_dois(facts.identifiers)
    if own and all(doi.split("/", 1)[0] in EXCLUDED_DOI_PREFIXES for doi in own):
        return False
    if facts.source == Source.DATACITE and facts.primary_doi_has_target:
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
