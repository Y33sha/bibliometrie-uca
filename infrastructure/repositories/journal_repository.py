"""Adapter PostgreSQL pour la persistance des journaux et éditeurs.

Un seul repository pour les deux tables (`journals` et `publishers`)
car leurs opérations sont étroitement couplées (fusions, rattachements
éditeur ↔ journal, formes de nom par entité).

Même contrat que les autres PgXxxRepository : curseur dans la
transaction courante, exceptions du domaine, pas d'orchestration
métier (qui reste dans services/journals.py).
"""

from utils.db_helpers import row_val as _val


class PgJournalRepository:
    """Accès PostgreSQL aux agrégats Journal et Publisher."""

    def __init__(self, cur):
        self._cur = cur

    # ── publisher_name_forms ───────────────────────────────────────

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        """Ajoute une forme de nom d'éditeur si elle n'existe pas (idempotent)."""
        self._cur.execute(
            """
            INSERT INTO publisher_name_forms (publisher_id, form_normalized)
            VALUES (%s, %s)
            ON CONFLICT (form_normalized) DO NOTHING
            """,
            (publisher_id, form_normalized),
        )

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        """Cherche un publisher_id via une forme de nom normalisée."""
        self._cur.execute(
            """
            SELECT publisher_id FROM publisher_name_forms
            WHERE form_normalized = %s LIMIT 1
            """,
            (form_normalized,),
        )
        row = self._cur.fetchone()
        return _val(row, 0) if row else None

    # ── publishers ─────────────────────────────────────────────────

    def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None:
        """Cherche un publisher par son openalex_id."""
        self._cur.execute(
            "SELECT id FROM publishers WHERE openalex_id = %s",
            (openalex_id,),
        )
        row = self._cur.fetchone()
        return _val(row, 0) if row else None

    def set_publisher_openalex_id_if_missing(
        self, publisher_id: int, openalex_id: str,
    ) -> None:
        """Attribue un openalex_id au publisher s'il n'en a pas déjà un."""
        self._cur.execute(
            """
            UPDATE publishers SET openalex_id = %s
            WHERE id = %s AND openalex_id IS NULL
            """,
            (openalex_id, publisher_id),
        )

    def create_publisher(
        self, *, name: str, name_normalized: str, openalex_id: str | None,
    ) -> int:
        """Insère un publisher et retourne son id."""
        self._cur.execute(
            """
            INSERT INTO publishers (name, name_normalized, openalex_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (name, name_normalized, openalex_id),
        )
        return _val(self._cur.fetchone(), 0)
