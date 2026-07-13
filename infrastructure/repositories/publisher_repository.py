"""Adapter PostgreSQL pour l'agrégat Publisher.

Séparé de `journal_repository.py` (principe ISP). Même contrat que
les autres PgXxxRepository : exceptions du domaine, pas
d'orchestration métier (qui reste dans `application/journals.py`).

La méthode `merge_publisher_into` réalise les étapes 2-6 d'une fusion
d'éditeurs ; la détection préalable des journaux à titre partagé
(étape 1) est dans `JournalRepository.find_shared_title_journal_pairs`
— le service `application/journals.merge_publishers` orchestre les
deux.
"""

from typing import NamedTuple, cast

from sqlalchemy import Connection, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.publisher_repository import PublisherUpdateFields
from domain.publishers.publisher import Publisher, PublisherType
from infrastructure.db.tables import publisher_name_forms, publishers
from infrastructure.queries.pipeline.pub_counts import refresh_publisher_pub_count


class _PublisherRow(NamedTuple):
    """Projection SQL `find_by_id` sur `publishers`."""

    id: int
    name: str
    country: str | None
    openalex_id: str | None
    ror: str | None
    is_predatory: bool
    publisher_type: str


def _publisher_from_row(row: _PublisherRow) -> Publisher:
    """Mapping d'une row `publishers` SQL vers l'aggregate `Publisher`."""
    return Publisher(
        id=row.id,
        name=row.name,
        country=row.country,
        openalex_id=row.openalex_id,
        ror=row.ror,
        is_predatory=row.is_predatory,
        publisher_type=cast(PublisherType, row.publisher_type),
    )


class PgPublisherRepository:
    """Accès PostgreSQL à l'agrégat Publisher via une `Connection` SA."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, publisher_id: int) -> Publisher | None:
        row = self._conn.execute(
            select(
                publishers.c.id,
                publishers.c.name,
                publishers.c.country,
                publishers.c.openalex_id,
                publishers.c.ror,
                publishers.c.is_predatory,
                publishers.c.publisher_type,
            ).where(publishers.c.id == publisher_id)
        ).first()
        if row is None:
            return None
        return _publisher_from_row(_PublisherRow(*row))

    # ── publisher_name_forms ───────────────────────────────────────

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        """Ajoute une forme de nom d'éditeur si elle n'existe pas (idempotent)."""
        stmt = (
            pg_insert(publisher_name_forms)
            .values(publisher_id=publisher_id, form_normalized=form_normalized)
            .on_conflict_do_nothing(index_elements=["form_normalized"])
        )
        self._conn.execute(stmt)

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        """Cherche un publisher_id via une forme de nom normalisée."""
        return self._conn.execute(
            select(publisher_name_forms.c.publisher_id)
            .where(publisher_name_forms.c.form_normalized == form_normalized)
            .limit(1)
        ).scalar_one_or_none()

    # ── publishers ─────────────────────────────────────────────────

    def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None:
        """Cherche un publisher par son openalex_id."""
        return self._conn.execute(
            select(publishers.c.id).where(publishers.c.openalex_id == openalex_id)
        ).scalar_one_or_none()

    def set_publisher_openalex_id_if_missing(
        self,
        publisher_id: int,
        openalex_id: str,
    ) -> None:
        """Attribue un openalex_id au publisher s'il n'en a pas déjà un."""
        stmt = (
            update(publishers)
            .where(publishers.c.id == publisher_id)
            .where(publishers.c.openalex_id.is_(None))
            .values(openalex_id=openalex_id)
        )
        self._conn.execute(stmt)

    def create_publisher(
        self,
        *,
        name: str,
        name_normalized: str,
        openalex_id: str | None,
    ) -> int:
        """Insère un publisher et retourne son id."""
        stmt = (
            publishers.insert()
            .values(name=name, name_normalized=name_normalized, openalex_id=openalex_id)
            .returning(publishers.c.id)
        )
        return self._conn.execute(stmt).scalar_one()

    def publisher_exists(self, publisher_id: int) -> bool:
        """Vérifie l'existence d'un publisher."""
        return (
            self._conn.execute(
                select(publishers.c.id).where(publishers.c.id == publisher_id)
            ).first()
            is not None
        )

    def update_publisher_fields(self, publisher_id: int, fields: PublisherUpdateFields) -> None:
        """UPDATE dynamique sur publishers."""
        stmt = update(publishers).where(publishers.c.id == publisher_id).values(**fields)
        self._conn.execute(stmt)

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
        self._conn.execute(
            text("UPDATE journals SET publisher_id = :t WHERE publisher_id = :s"),
            {"t": target_id, "s": source_id},
        )

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

        # journal_name_forms : supprime d'abord les doublons avec target,
        # puis transfère le reste.
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

        self._conn.execute(
            text("UPDATE apc_payments SET publisher_id = :t WHERE publisher_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # Ordre : capture src → NULL-er openalex_id src (libère la contrainte
        # UNIQUE — `ror` n'a pas de UNIQUE, plusieurs publishers peuvent
        # légitimement le partager) → enrich target → delete source.
        src = self._conn.execute(
            select(
                publishers.c.openalex_id,
                publishers.c.ror,
                publishers.c.country,
                publishers.c.is_predatory,
            ).where(publishers.c.id == source_id)
        ).one()
        self._conn.execute(
            update(publishers).where(publishers.c.id == source_id).values(openalex_id=None)
        )
        self._conn.execute(
            update(publishers)
            .where(publishers.c.id == target_id)
            .values(
                openalex_id=func.coalesce(publishers.c.openalex_id, src.openalex_id),
                ror=func.coalesce(publishers.c.ror, src.ror),
                country=func.coalesce(publishers.c.country, src.country),
                is_predatory=publishers.c.is_predatory | src.is_predatory,
            )
        )

        self._conn.execute(delete(publishers).where(publishers.c.id == source_id))

        # pub_count : la cible a absorbé les revues de la source (les pub_count des
        # revues sont inchangés) → recalcule la somme côté éditeur cible.
        refresh_publisher_pub_count(self._conn, target_id)
