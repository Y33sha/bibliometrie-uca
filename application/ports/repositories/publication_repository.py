"""Port PublicationRepository — contrat d'accès à l'agrégat Publication.

Implémenté par infrastructure/repositories/publication_repository.py.
"""

from dataclasses import dataclass
from typing import Protocol

from domain.publications.publication import Publication
from domain.source_publications.source_publication import SourcePublication


@dataclass(frozen=True, slots=True)
class PubByDoi:
    """Projection de lecture retournée par `find_by_doi` : l'id de la publication
    portant ce DOI, sans hydrater l'agrégat complet."""

    id: int


class PublicationRepository(Protocol):
    """Contrat d'accès à l'agrégat Publication (tables publications,
    source_publications et distinct_publications)."""

    # ── Chargement / persistance de l'aggregate ────────────────────

    def find_by_id(self, pub_id: int) -> Publication | None: ...

    def save(self, pub: Publication) -> None: ...

    # ── Recherches (projections de lecture) ────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None: ...

    def find_ids_by_journal_id(self, journal_id: int) -> list[int]:
        """Ids des publications rattachées à ce journal. Utilisé pour requalifier le stock quand un input éditable du journal (ex. `journal_type`) change."""
        ...

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None: ...

    def mark_unpaywall_checked(self, pub_id: int) -> None: ...

    def update_sources(self, pub_id: int) -> None: ...

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_publications(self, pub_id: int) -> list[SourcePublication]: ...

    def get_converged_secondary_ids(self, pub_id: int) -> frozenset[int]:
        """Ids des `source_publications` de `pub_id` dont le DOI a été substitué par une correction de convergence (forme secondaire : version, variante, pièce d'un dataset). L'agrégation les déprioris pour que les scalaires descriptifs viennent de l'enregistrement canonique."""
        ...

    def get_journal_type(self, journal_id: int) -> str | None:
        """`journal_type` d'un journal, pour la re-correction canonique journal-dépendante dans `refresh_from_sources`. None si le journal n'existe pas ou son type n'est pas posé."""
        ...

    # ── Création ───────────────────────────────────────────────────

    def create(
        self,
        *,
        title: str,
        title_normalized: str,
        doc_type: str,
        pub_year: int,
        doi: str | None,
        oa_status: str,
    ) -> int: ...

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_into(self, target_id: int, source_id: int) -> None: ...

    # ── Suppression ────────────────────────────────────────────────

    def delete(self, pub_id: int) -> None: ...

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(
        self,
        pub_id_a: int,
        pub_id_b: int,
    ) -> tuple[int, int] | None: ...
