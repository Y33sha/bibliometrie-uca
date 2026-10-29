"""Périmètre des publications : types de document admissibles, enregistrements sources écartés."""

from collections.abc import Sequence, Set
from typing import NamedTuple

from domain.publications.identifiers import DOI
from domain.publications.metadata import normalized_title
from domain.source_records.identifiers import SourceIdentifier, active
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

    `raw_doi` est le DOI d'avant correction. `doi` et `urls` sont les valeurs corrigées, privées des dépôts HAL introuvables. `identifiers` sont les identifiants de l'enregistrement source, avec leur statut. `raw_doi_has_target` : `raw_doi` est le DOI d'une forme secondaire, qui a une cible dans `doi_targets`.
    """

    source: str
    source_id: str
    raw_doi: str | None
    doi: str | None
    title_normalized: str | None
    urls: Sequence[str]
    identifiers: Sequence[SourceIdentifier]
    raw_doi_has_target: bool = False


def is_matchable(facts: MatchabilityFacts, missing_hal_ids: Set[str]) -> bool:
    """Vrai si l'enregistrement source entre dans la réconciliation. Il en est écarté si :

    - son DOI d'avant correction a un préfixe de `EXCLUDED_DOI_PREFIXES` ;
    - il vient de DataCite et son DOI d'avant correction a une cible : l'enregistrement source est une forme secondaire d'une œuvre présente en base ;
    - son titre normalisé est dans `PARATEXT_TITLES` ;
    - il vient de ScanR et il est issu d'un dépôt HAL de `missing_hal_ids` ;
    - il vient d'une source de `AGGREGATOR_SOURCES` et il n'a ni DOI, ni lien, ni clé de confirmation active.
    """
    raw_doi = DOI.try_parse(facts.raw_doi)
    if raw_doi is not None and raw_doi.prefix.value in EXCLUDED_DOI_PREFIXES:
        return False
    if facts.source == Source.DATACITE and facts.raw_doi_has_target:
        return False
    if facts.title_normalized in PARATEXT_TITLES:
        return False
    if facts.source == Source.SCANR and (
        extract_hal_id_from_scanr_id(facts.source_id) in missing_hal_ids
    ):
        return False
    if facts.source in AGGREGATOR_SOURCES:
        return bool(
            facts.doi
            or facts.urls
            or any(i.id_type in CONFIRMATION_ID_TYPES for i in active(facts.identifiers))
        )
    return True
