"""Périmètre des publications : types de document admissibles, enregistrements sources écartés."""

from collections.abc import Mapping, Sequence, Set
from typing import NamedTuple

from domain.publications.identifiers import DOI
from domain.publications.metadata import normalized_title
from domain.source_records.keys import CONFIRMATION_ID_TYPES
from domain.sources.registry import AGGREGATOR_SOURCES, Source
from domain.sources.scanr import extract_hal_id_from_scanr_id
from domain.types import JsonValue

OUT_OF_SCOPE_DOC_TYPES = frozenset({"peer_review", "memoir", "physical_object"})
"""Types de document non admissibles : jamais matérialisés en publication.

Une œuvre dont le `doc_type` canonique résolu appartient à cet ensemble n'a pas de ligne
`publications` : le module du cycle de vie la supprime après l'arbitrage du type
(`pipeline/transformation/publications/lifecycle.py`). Ses `source_records` et
`source_contributions` subsistent, détachées : sans publication, elles ne génèrent ni
contribution canonique ni personne.

Justifications :

- `peer_review` : reviews de papers, pas une contribution scientifique en soi (les
  comptes de publications seraient pollués).
- `memoir` : essentiellement DUMAS (Master), étudiants pas membres permanents — les
  inclure polluerait `persons` de comptes éphémères.
- `physical_object` : échantillon ou instrument identifié par un DOI DataCite (IGSN des
  échantillothèques), pas un texte publié.

Deux points d'application : un enregistrement de l'un de ces types ne fonde pas de publication
à la réconciliation (`domain/publications/reconciliation.py`), et le module du cycle de vie
supprime la publication dont le type résolu est de cet ensemble. Retirer un type de cet
ensemble suffit à le réintégrer à la matérialisation.
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

    `raw_doi` est le DOI d'avant correction. `doi`, `urls` et `external_ids` sont les valeurs corrigées, privées des dépôts HAL introuvables.
    """

    source: str
    source_id: str
    raw_doi: str | None
    doi: str | None
    title_normalized: str | None
    urls: Sequence[str]
    external_ids: Mapping[str, JsonValue]


def is_matchable(facts: MatchabilityFacts, missing_hal_ids: Set[str]) -> bool:
    """L'enregistrement source entre dans la réconciliation. Il en est écarté dans quatre cas :

    - son DOI d'avant correction a un préfixe de `EXCLUDED_DOI_PREFIXES` ;
    - son titre normalisé est dans `PARATEXT_TITLES` ;
    - il vient de ScanR et il est issu d'un dépôt HAL de `missing_hal_ids` ;
    - il vient d'une source de `AGGREGATOR_SOURCES` et il n'a ni DOI, ni lien, ni clé de confirmation.
    """
    raw_doi = DOI.try_parse(facts.raw_doi)
    if raw_doi is not None and raw_doi.prefix.value in EXCLUDED_DOI_PREFIXES:
        return False
    if facts.title_normalized in PARATEXT_TITLES:
        return False
    if facts.source == Source.SCANR and (
        extract_hal_id_from_scanr_id(facts.source_id) in missing_hal_ids
    ):
        return False
    if facts.source in AGGREGATOR_SOURCES:
        return bool(
            facts.doi or facts.urls or any(facts.external_ids.get(t) for t in CONFIRMATION_ID_TYPES)
        )
    return True
