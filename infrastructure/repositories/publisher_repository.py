"""Adapter PostgreSQL pour l'agrégat Publisher.

Séparé de `journal_repository.py` (principe ISP). Même contrat que
les autres PgXxxRepository : curseur dans la transaction courante,
exceptions du domaine, pas d'orchestration métier (qui reste dans
`application/journals.py`).

La méthode `merge_publisher_into` réalise les étapes 2-6 d'une fusion
d'éditeurs ; la détection préalable des journaux à titre partagé
(étape 1) est dans `JournalRepository.find_shared_title_journal_pairs`
— le service `application/journals.merge_publishers` orchestre les
deux.
"""

from typing import Any

from infrastructure.db_helpers import row_val as _val


class PgPublisherRepository:
    """Accès PostgreSQL à l'agrégat Publisher."""

    def __init__(self, cur: Any) -> None:
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
        self,
        publisher_id: int,
        openalex_id: str,
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
        self,
        *,
        name: str,
        name_normalized: str,
        openalex_id: str | None,
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

    def publisher_exists(self, publisher_id: int) -> bool:
        """Vérifie l'existence d'un publisher."""
        self._cur.execute("SELECT id FROM publishers WHERE id = %s", (publisher_id,))
        return self._cur.fetchone() is not None

    def update_publisher_fields(self, publisher_id: int, fields: dict) -> None:
        """UPDATE dynamique sur publishers."""
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._cur.execute(
            f"UPDATE publishers SET {sets}, updated_at = now() WHERE id = %s",
            list(fields.values()) + [publisher_id],
        )

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        """Fusion d'éditeur — étapes 2-6 (le service a déjà traité les paires
        de journaux partageant un titre via `find_shared_title_journal_pairs`
        + merge_journals).

        1. (fait côté service) fusion des journaux à titres partagés
        2. Transfert des journaux restants vers la cible
        3. Transfert/dédup des publisher_name_forms
        3b. Transfert/dédup des journal_name_forms référençant le publisher
        4. Transfert des apc_payments
        5. Enrichissement des champs (openalex_id, country, is_predatory)
        6. Suppression de l'éditeur source
        """
        # 2. Transférer les journals restants
        self._cur.execute(
            "UPDATE journals SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 3. Transférer les publisher_name_forms (dédup sur form_normalized)
        self._cur.execute(
            """
            UPDATE publisher_name_forms SET publisher_id = %s
            WHERE publisher_id = %s
              AND form_normalized NOT IN (
                  SELECT form_normalized FROM publisher_name_forms WHERE publisher_id = %s
              )
            """,
            (target_id, source_id, target_id),
        )
        self._cur.execute(
            "DELETE FROM publisher_name_forms WHERE publisher_id = %s",
            (source_id,),
        )

        # 3b. journal_name_forms (supprime d'abord les doublons avec target,
        # puis transfère le reste)
        self._cur.execute(
            """
            DELETE FROM journal_name_forms
            WHERE publisher_id = %s
              AND form_normalized IN (
                  SELECT form_normalized FROM journal_name_forms WHERE publisher_id = %s
              )
            """,
            (source_id, target_id),
        )
        self._cur.execute(
            "UPDATE journal_name_forms SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 4. Transférer les apc_payments
        self._cur.execute(
            "UPDATE apc_payments SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 5. Enrichir la cible. Ordre : capture src → NULL-er openalex_id src
        # (libère la contrainte UNIQUE) → enrich target → delete source.
        self._cur.execute(
            "SELECT openalex_id, country, is_predatory FROM publishers WHERE id = %s",
            (source_id,),
        )
        src = self._cur.fetchone()
        self._cur.execute(
            "UPDATE publishers SET openalex_id = NULL WHERE id = %s",
            (source_id,),
        )
        self._cur.execute(
            """
            UPDATE publishers SET
                openalex_id = COALESCE(openalex_id, %s),
                country = COALESCE(country, %s),
                is_predatory = is_predatory OR %s,
                updated_at = now()
            WHERE id = %s
            """,
            (src["openalex_id"], src["country"], src["is_predatory"], target_id),
        )

        # 6. Supprimer la source
        self._cur.execute("DELETE FROM publishers WHERE id = %s", (source_id,))
