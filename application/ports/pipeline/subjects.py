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

    def clear_publication_subjects_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> int:
        """`DELETE` des liens (non rejetés) des publications données, toutes
        sources. Préserve les liens rejetés. Retourne le rowcount."""
        ...

    def select_publications_to_reingest(self, conn: Connection) -> list[int]:
        """Ids des publications dont les sujets sont à (ré)ingérer : contenu
        canonique modifié depuis la dernière ingestion (`publications.updated_at`
        > `max(publication_subjects.created_at)`), ou jamais ingérées."""
        ...

    def select_source_publications_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> list[Any]:
        """`source_publications` (id, publication_id, source, keywords, topics)
        des publications données — matière première par-source de la
        ré-ingestion."""
        ...

    def purge_orphan_subjects(self, conn: Connection) -> int:
        """`DELETE` des sujets sans aucun lien `publication_subjects` (tous
        statuts). Retourne le nombre supprimé."""
        ...

    def recompute_usage_counts(self, conn: Connection) -> int:
        """Recalcule `subjects.usage_count` depuis `publication_subjects`."""
        ...

    def refresh_cooccurrences(self, conn: Connection) -> int:
        """Rafraîchit la matview `subject_cooccurrences`. Retourne le nombre
        de paires après refresh (seuil `count >= 2` figé dans la matview)."""
        ...
