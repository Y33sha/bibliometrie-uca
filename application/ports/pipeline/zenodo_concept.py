"""Port : SQL de la sous-étape de résolution du concept DOI Zenodo.

Implémenté par `infrastructure.queries.publications.zenodo_concept.PgZenodoConceptQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class ZenodoSourcePublication(NamedTuple):
    """Source_publication au DOI Zenodo restant à résoudre (concept absent)."""

    id: int
    doi: str


class ZenodoConceptQueries(Protocol):
    """Opérations SQL de la résolution du concept DOI Zenodo."""

    def fetch_zenodo_source_publications_without_concept(
        self, conn: Connection
    ) -> list[ZenodoSourcePublication]:
        """source_publications au DOI Zenodo sans `external_ids.zenodo_concept_doi`.

        Les SP déjà résolues sont exclues : la sous-étape est donc relançable
        sans rappeler l'API pour les DOI déjà traités.
        """

    def set_concept_doi(
        self, conn: Connection, source_publication_id: int, concept_doi: str
    ) -> None:
        """Pose `external_ids.zenodo_concept_doi` sur une source_publication."""
