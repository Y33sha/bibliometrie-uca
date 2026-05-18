"""Port : opérations SQL pour la phase d'ingestion des sujets / mots-clés
et le recalcul des co-occurrences.

Implémenté par `infrastructure.queries.subjects.PgSubjectsQueries`.
"""

from typing import Any, Protocol, TypedDict

from sqlalchemy import Connection


class OntologyEntry(TypedDict, total=False):
    """Annotation d'une ontologie sur un sujet : codes + niveau hiérarchique.

    Toutes les clés sont optionnelles (`total=False`) pour couvrir les cas
    où seul `codes` est fourni (la plupart des sources : HAL domain, WoS
    headings, ScanR domain, theses discipline) ou où `level`/`parent` sont
    fournis en plus (OpenAlex topics avec leur chaîne hiérarchique).

    Au `ON CONFLICT` de `upsert_subject`, les `codes` sont unionnés ;
    `level` et `parent` gardent la première valeur non-null (existant
    prioritaire).
    """

    codes: list[str]
    level: int | None
    parent: str | None


class SubjectsQueries(Protocol):
    """Toutes les opérations SQL nécessaires aux phases `subjects` et
    `cooccurrences`."""

    def upsert_subject(
        self,
        conn: Connection,
        *,
        label: str,
        language: str | None = None,
        ontologies: dict[str, OntologyEntry] | None = None,
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
        conn: Connection,
        *,
        source: str,
        rows: list[tuple[int, int, float | None]],
    ) -> int:
        """Bulk INSERT (avec ON CONFLICT) de liens publication↔subject pour
        une source. Dédoublonne `(pub_id, subject_id)` côté client."""
        ...

    def clear_links_for_source(self, conn: Connection, *, source: str) -> int:
        """`DELETE FROM publication_subjects WHERE source = X`. Retourne le rowcount."""
        ...

    def select_source_publications_with_subjects(
        self, conn: Connection, *, source: str
    ) -> list[Any]:
        """Retourne les `source_publications` rattachées (publication_id non NULL)
        pour la source donnée, avec leurs `keywords` et `topics`."""
        ...

    def recompute_usage_counts(self, conn: Connection) -> int:
        """Recalcule `subjects.usage_count` depuis `publication_subjects`."""
        ...

    def recompute_cooccurrences(self, conn: Connection, *, min_count: int = 2) -> int:
        """Recalcule la table `subject_cooccurrences` (TRUNCATE + INSERT)."""
        ...
