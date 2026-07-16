"""Port : opérations SQL pour la phase d'ingestion des sujets et le recalcul des co-occurrences.

Implémenté par `infrastructure.queries.subjects.PgSubjectsQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class SourcePublicationTopics(NamedTuple):
    """Le champ `topics` d'une `source_publication`, avec sa publication et sa source — matière première par-source de la ré-ingestion des concepts."""

    publication_id: int
    source: str
    topics: JsonValue


class PublicationSubjectLink(NamedTuple):
    """Lien à créer entre une publication et un sujet du référentiel."""

    publication_id: int
    subject_id: int


class SubjectsQueries(Protocol):
    """Toutes les opérations SQL nécessaires aux phases `subjects` et `cooccurrences`."""

    def upsert_subject(
        self,
        conn: Connection,
        *,
        label: str,
        language: str | None = None,
    ) -> int:
        """UPSERT d'un sujet (clé d'unicité = lower(label)). Retourne l'id.

        Au `ON CONFLICT`, la `language` déjà posée est conservée (premier non-null gagne)."""
        ...

    def link_publication_subjects_bulk(
        self,
        conn: Connection,
        *,
        source: str,
        rows: list[PublicationSubjectLink],
    ) -> int:
        """Bulk INSERT (avec ON CONFLICT) de liens publication↔subject pour une source. Dédoublonne `(pub_id, subject_id)` côté client."""
        ...

    def clear_publication_subjects_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> int:
        """`DELETE` des liens (non rejetés) des publications données, toutes sources. Préserve les liens rejetés. Retourne le rowcount."""
        ...

    def select_publications_to_reingest(self, conn: Connection) -> list[int]:
        """Ids des publications dont les sujets sont à (ré)ingérer : contenu canonique modifié depuis la dernière ingestion (`publications.updated_at` > `max(publication_subjects.created_at)`), ou jamais ingérées."""
        ...

    def select_all_publication_ids(self, conn: Connection) -> list[int]:
        """Ids de toutes les publications — pour une ré-ingestion complète (`rebuild`), indépendante du signal incrémental."""
        ...

    def select_source_publications_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> list[SourcePublicationTopics]:
        """Le `topics` de chaque `source_publication` des publications données, avec sa source."""
        ...

    def purge_orphan_subjects(self, conn: Connection) -> int:
        """`DELETE` des sujets sans aucun lien `publication_subjects` (tous statuts). Retourne le nombre supprimé."""
        ...

    def count_subjects(self, conn: Connection) -> int:
        """Nombre total de sujets du référentiel (`COUNT(*)` sur `subjects`)."""
        ...

    def recompute_usage_counts(self, conn: Connection) -> int:
        """Recalcule `subjects.usage_count` depuis `publication_subjects`."""
        ...

    def refresh_cooccurrences(self, conn: Connection) -> int:
        """Rafraîchit la matview `subject_cooccurrences`. Retourne le nombre de paires après refresh (seuil `count >= 2` figé dans la matview)."""
        ...
