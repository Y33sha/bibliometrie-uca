"""Port : opérations SQL pour la phase d'ingestion des sujets/mots-clés.

Implémenté par `infrastructure.db.queries.subjects.PgSubjectsQueries`.
Utilisé par `application.pipeline.subjects.run` (orchestrateur) et par le
`SubjectCache` (cache mémoire des subject_id partagé entre publications).
"""

from typing import Any, Protocol


class SubjectsQueries(Protocol):
    """Toutes les opérations SQL nécessaires à la phase `subjects`."""

    def upsert_free_subject(self, cur: Any, *, label: str, language: str | None = None) -> int: ...

    def upsert_concept_subject(
        self,
        cur: Any,
        *,
        ontology: str,
        ontology_id: str,
        label: str,
        language: str | None = None,
        parent_id: int | None = None,
        level: int | None = None,
    ) -> int: ...

    def link_publication_subjects_bulk(
        self,
        cur: Any,
        *,
        source: str,
        rows: list[tuple[int, int, float | None]],
    ) -> int: ...

    def clear_links_for_source(self, cur: Any, *, source: str) -> int:
        """`DELETE FROM publication_subjects WHERE source = X`. Retourne le rowcount."""
        ...

    def select_source_publications_with_subjects(self, cur: Any, *, source: str) -> list[Any]:
        """Retourne les `source_publications` rattachées (publication_id non NULL)
        pour la source donnée, avec leurs `keywords` et `topics`. Chaque ligne
        est un dict (ou tuple) avec les clés `publication_id`, `keywords`, `topics`."""
        ...
