"""Adapter PostgreSQL pour l'agrégat Publisher.

Séparé de `journal_repository.py` (principe ISP). Même contrat que
les autres PgXxxRepository : exceptions du domaine, pas
d'orchestration métier (qui reste dans `application/journals.py`).

La méthode `merge_publisher_into` réalise les étapes 2-6 d'une fusion
d'éditeurs ; la détection préalable des journaux à titre partagé
(étape 1) est dans `JournalRepository.find_shared_title_journal_pairs`
— le service `application/journals.merge_publishers` orchestre les
deux.

Mode dispatch (cur psycopg | Connection SA) pour cohabiter avec le
chantier sqlalchemy-core-adoption. La branche SA utilise la MetaData
explicite ; la branche psycopg conserve le code existant. Phase 4
supprimera la branche psycopg.
"""

from typing import Any

from sqlalchemy import Connection, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrastructure.db.tables import publisher_name_forms, publishers
from infrastructure.db_helpers import row_val as _val


class PgPublisherRepository:
    """Accès PostgreSQL à l'agrégat Publisher.

    Accepte un curseur psycopg ou une Connection SQLAlchemy.
    """

    def __init__(self, conn_or_cur: Any) -> None:
        self._conn = conn_or_cur
        self._is_sa = isinstance(conn_or_cur, Connection)

    # ── publisher_name_forms ───────────────────────────────────────

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        """Ajoute une forme de nom d'éditeur si elle n'existe pas (idempotent)."""
        if self._is_sa:
            stmt = (
                pg_insert(publisher_name_forms)
                .values(publisher_id=publisher_id, form_normalized=form_normalized)
                .on_conflict_do_nothing(index_elements=["form_normalized"])
            )
            self._conn.execute(stmt)
            return
        self._conn.execute(
            """
            INSERT INTO publisher_name_forms (publisher_id, form_normalized)
            VALUES (%s, %s)
            ON CONFLICT (form_normalized) DO NOTHING
            """,
            (publisher_id, form_normalized),
        )

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        """Cherche un publisher_id via une forme de nom normalisée."""
        if self._is_sa:
            result = self._conn.execute(
                select(publisher_name_forms.c.publisher_id)
                .where(publisher_name_forms.c.form_normalized == form_normalized)
                .limit(1)
            )
            return result.scalar_one_or_none()
        self._conn.execute(
            """
            SELECT publisher_id FROM publisher_name_forms
            WHERE form_normalized = %s LIMIT 1
            """,
            (form_normalized,),
        )
        row = self._conn.fetchone()
        return _val(row, 0) if row else None

    # ── publishers ─────────────────────────────────────────────────

    def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None:
        """Cherche un publisher par son openalex_id."""
        if self._is_sa:
            result = self._conn.execute(
                select(publishers.c.id).where(publishers.c.openalex_id == openalex_id)
            )
            return result.scalar_one_or_none()
        self._conn.execute(
            "SELECT id FROM publishers WHERE openalex_id = %s",
            (openalex_id,),
        )
        row = self._conn.fetchone()
        return _val(row, 0) if row else None

    def set_publisher_openalex_id_if_missing(
        self,
        publisher_id: int,
        openalex_id: str,
    ) -> None:
        """Attribue un openalex_id au publisher s'il n'en a pas déjà un."""
        if self._is_sa:
            stmt = (
                update(publishers)
                .where(publishers.c.id == publisher_id)
                .where(publishers.c.openalex_id.is_(None))
                .values(openalex_id=openalex_id)
            )
            self._conn.execute(stmt)
            return
        self._conn.execute(
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
        if self._is_sa:
            stmt = (
                publishers.insert()
                .values(name=name, name_normalized=name_normalized, openalex_id=openalex_id)
                .returning(publishers.c.id)
            )
            result = self._conn.execute(stmt)
            return result.scalar_one()
        self._conn.execute(
            """
            INSERT INTO publishers (name, name_normalized, openalex_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (name, name_normalized, openalex_id),
        )
        return _val(self._conn.fetchone(), 0)

    def publisher_exists(self, publisher_id: int) -> bool:
        """Vérifie l'existence d'un publisher."""
        if self._is_sa:
            result = self._conn.execute(
                select(publishers.c.id).where(publishers.c.id == publisher_id)
            )
            return result.first() is not None
        self._conn.execute("SELECT id FROM publishers WHERE id = %s", (publisher_id,))
        return self._conn.fetchone() is not None

    def update_publisher_fields(self, publisher_id: int, fields: dict) -> None:
        """UPDATE dynamique sur publishers."""
        if self._is_sa:
            stmt = (
                update(publishers)
                .where(publishers.c.id == publisher_id)
                .values(**fields, updated_at=func.now())
            )
            self._conn.execute(stmt)
            return
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._conn.execute(
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
        if self._is_sa:
            # 2. Transférer les journals restants
            self._conn.execute(
                text("UPDATE journals SET publisher_id = :t WHERE publisher_id = :s"),
                {"t": target_id, "s": source_id},
            )

            # 3. Transférer les publisher_name_forms (dédup sur form_normalized)
            self._conn.execute(
                text("""
                    UPDATE publisher_name_forms SET publisher_id = :t
                    WHERE publisher_id = :s
                      AND form_normalized NOT IN (
                          SELECT form_normalized FROM publisher_name_forms
                          WHERE publisher_id = :t
                      )
                """),
                {"t": target_id, "s": source_id},
            )
            self._conn.execute(
                delete(publisher_name_forms).where(publisher_name_forms.c.publisher_id == source_id)
            )

            # 3b. journal_name_forms (supprime d'abord les doublons avec target,
            # puis transfère le reste)
            self._conn.execute(
                text("""
                    DELETE FROM journal_name_forms
                    WHERE publisher_id = :s
                      AND form_normalized IN (
                          SELECT form_normalized FROM journal_name_forms
                          WHERE publisher_id = :t
                      )
                """),
                {"t": target_id, "s": source_id},
            )
            self._conn.execute(
                text("UPDATE journal_name_forms SET publisher_id = :t WHERE publisher_id = :s"),
                {"t": target_id, "s": source_id},
            )

            # 4. Transférer les apc_payments
            self._conn.execute(
                text("UPDATE apc_payments SET publisher_id = :t WHERE publisher_id = :s"),
                {"t": target_id, "s": source_id},
            )

            # 5. Enrichir la cible. Ordre : capture src → NULL-er openalex_id src
            # (libère la contrainte UNIQUE) → enrich target → delete source.
            result = self._conn.execute(
                select(
                    publishers.c.openalex_id, publishers.c.country, publishers.c.is_predatory
                ).where(publishers.c.id == source_id)
            )
            src = result.one()
            self._conn.execute(
                update(publishers).where(publishers.c.id == source_id).values(openalex_id=None)
            )
            self._conn.execute(
                update(publishers)
                .where(publishers.c.id == target_id)
                .values(
                    openalex_id=func.coalesce(publishers.c.openalex_id, src.openalex_id),
                    country=func.coalesce(publishers.c.country, src.country),
                    is_predatory=publishers.c.is_predatory | src.is_predatory,
                    updated_at=func.now(),
                )
            )

            # 6. Supprimer la source
            self._conn.execute(delete(publishers).where(publishers.c.id == source_id))
            return

        # 2. Transférer les journals restants
        self._conn.execute(
            "UPDATE journals SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 3. Transférer les publisher_name_forms (dédup sur form_normalized)
        self._conn.execute(
            """
            UPDATE publisher_name_forms SET publisher_id = %s
            WHERE publisher_id = %s
              AND form_normalized NOT IN (
                  SELECT form_normalized FROM publisher_name_forms WHERE publisher_id = %s
              )
            """,
            (target_id, source_id, target_id),
        )
        self._conn.execute(
            "DELETE FROM publisher_name_forms WHERE publisher_id = %s",
            (source_id,),
        )

        # 3b. journal_name_forms (supprime d'abord les doublons avec target,
        # puis transfère le reste)
        self._conn.execute(
            """
            DELETE FROM journal_name_forms
            WHERE publisher_id = %s
              AND form_normalized IN (
                  SELECT form_normalized FROM journal_name_forms WHERE publisher_id = %s
              )
            """,
            (source_id, target_id),
        )
        self._conn.execute(
            "UPDATE journal_name_forms SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 4. Transférer les apc_payments
        self._conn.execute(
            "UPDATE apc_payments SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 5. Enrichir la cible. Ordre : capture src → NULL-er openalex_id src
        # (libère la contrainte UNIQUE) → enrich target → delete source.
        self._conn.execute(
            "SELECT openalex_id, country, is_predatory FROM publishers WHERE id = %s",
            (source_id,),
        )
        src = self._conn.fetchone()
        self._conn.execute(
            "UPDATE publishers SET openalex_id = NULL WHERE id = %s",
            (source_id,),
        )
        self._conn.execute(
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
        self._conn.execute("DELETE FROM publishers WHERE id = %s", (source_id,))
