"""Projections de lecture des publications et façade transitoire sur
les identifiants.

Contenu :
- Projections (`PubByDoi`, `PubByNnt`, `PubByTitle`, `PubThesisCandidate`) :
  formes de résultat renvoyées par `PublicationRepository`.
- Façade ré-exportant `DOI`, `HALId`, `NNT`, `clean_doi`,
  `normalize_nnt`, `extract_hal_id_from_url` depuis
  `domain/publications/identifiers.py` — les nouveaux call sites
  importent directement depuis le module spécialisé.

Les modèles des colonnes JSONB (`external_ids`, `biblio`, `meta`,
`topics`) vivent côté infrastructure
(`infrastructure/db/jsonb_models/publication.py`) — c'est un détail
d'adapter de persistance, pas du métier.

Règles métier réparties :
- Identifiants : `domain/publications/identifiers.py`
- Déduplication (`decide_publication_match`, `resolve_doi_conflict`) : `domain/publications/deduplication.py`
- Métadonnées (`best_oa_status`, `clean_publication_title`, `has_minimal_publication_metadata`,
  `OA_RANK`, `OA_STATUS_UNKNOWN_DEFAULT`) : `domain/publications/metadata.py`
"""

from dataclasses import dataclass

# Ré-exports — voir docstring du module.
from domain.publications.identifiers import (
    DOI,
    NNT,
    HALId,
    clean_doi,
    extract_hal_id_from_url,
    normalize_nnt,
)

__all__ = [
    "DOI",
    "HALId",
    "NNT",
    "clean_doi",
    "normalize_nnt",
    "extract_hal_id_from_url",
    "PubByDoi",
    "PubByNnt",
    "PubByTitle",
    "PubThesisCandidate",
]

# ── Types de résultats de recherche ────────────────────────────────
# Utilisés par le port PublicationRepository et ses implémentations.
# Vivent dans le domaine car ils décrivent la forme d'un résultat
# métier, pas un détail d'infrastructure.
#
# Dataclasses avec `slots=True` pour occuper le mappage fait par
# `psycopg.rows.class_row(...)` : les noms de champs correspondent aux
# colonnes SELECT du repo.


@dataclass(frozen=True, slots=True)
class PubByDoi:
    id: int
    doc_type: str | None
    title_normalized: str | None


@dataclass(frozen=True, slots=True)
class PubByNnt:
    id: int
    doc_type: str | None
    title_normalized: str | None


@dataclass(frozen=True, slots=True)
class PubByTitle:
    id: int
    doi: str | None


@dataclass(frozen=True, slots=True)
class PubThesisCandidate:
    id: int
    doi: str | None
