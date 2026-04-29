"""Port : opérations SQL pour la phase d'ingestion des sujets / mots-clés
et le recalcul des co-occurrences.

Implémenté par `infrastructure.db.queries.subjects.PgSubjectsQueries`.
"""

from typing import Any, Protocol


class SubjectsQueries(Protocol):
    """Toutes les opérations SQL nécessaires aux phases `subjects` et
    `cooccurrences`."""

    def upsert_subject(
        self,
        cur: Any,
        *,
        label: str,
        language: str | None = None,
        ontologies: dict[str, dict[str, Any]] | None = None,
    ) -> int:
        """UPSERT d'un sujet (clé d'unicité = lower(label)). Fusionne les
        annotations `ontologies` (union des codes par ontologie, premier
        non-null gagne pour `level` et `parent`) au `ON CONFLICT`. Retourne l'id.

        Format de `ontologies` :
            {
                "openalex_topic": {
                    "codes": ["computer science"],
                    "level": 2,
                    "parent": "Engineering",
                },
                "hal_domain": {"codes": ["info"]},
            }
        Vide ou None pour un libre.
        """
        ...

    def link_publication_subjects_bulk(
        self,
        cur: Any,
        *,
        source: str,
        rows: list[tuple[int, int, float | None]],
    ) -> int:
        """Bulk INSERT (avec ON CONFLICT) de liens publication↔subject pour
        une source. Dédoublonne `(pub_id, subject_id)` côté client."""
        ...

    def clear_links_for_source(self, cur: Any, *, source: str) -> int:
        """`DELETE FROM publication_subjects WHERE source = X`. Retourne le rowcount."""
        ...

    def select_source_publications_with_subjects(self, cur: Any, *, source: str) -> list[Any]:
        """Retourne les `source_publications` rattachées (publication_id non NULL)
        pour la source donnée, avec leurs `keywords` et `topics`."""
        ...

    def recompute_usage_counts(self, cur: Any) -> int:
        """Recalcule `subjects.usage_count` depuis `publication_subjects`."""
        ...

    def recompute_cooccurrences(self, cur: Any, *, min_count: int = 2) -> int:
        """Recalcule la table `subject_cooccurrences` (TRUNCATE + INSERT)."""
        ...
