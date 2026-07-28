"""Adapter PostgreSQL pour l'édition, l'enrichissement pays et la fusion de l'agrégat Publisher.

Séparé de `journal_repository.py` (principe ISP). Le trouve-ou-crée, alimenté par le pipeline, vit dans `infrastructure/pipeline/publishers.py`. Même contrat que les autres PgXxxRepository : exceptions du domaine, l'orchestration métier restant dans `application/services/`.

La méthode `merge_publisher_into` réalise les étapes 2-6 d'une fusion d'éditeurs ; la détection préalable des journaux à titre partagé (étape 1) est dans `JournalRepository.find_shared_title_journal_pairs`, le service de fusion d'éditeurs orchestrant les deux.
"""

from sqlalchemy import Connection, delete, func, select, text, update

from application.ports.repositories.publisher_repository import PublisherRepository, PublisherUpdate
from domain.errors import NotFoundError
from domain.normalize import normalize_text
from infrastructure.db.tables import publisher_name_forms, publishers
from infrastructure.pipeline.authorships.pub_counts import refresh_publisher_pub_count


class PgPublisherRepository(PublisherRepository):
    """Accès PostgreSQL à l'agrégat Publisher via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Lecture de commande ────────────────────────────────────────

    def exists(self, publisher_id: int) -> bool:
        return (
            self._conn.execute(
                select(publishers.c.id).where(publishers.c.id == publisher_id)
            ).first()
            is not None
        )

    # ── Enrichissement pays (maintenance) ──────────────────────────

    def find_needing_country_enrichment(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        rows = self._conn.execute(
            select(publishers.c.id, publishers.c.openalex_id)
            .where(publishers.c.openalex_id.is_not(None))
            .where(publishers.c.country.is_(None))
            .order_by(publishers.c.id)
            .limit(limit)
        ).all()
        return [(r.id, r.openalex_id) for r in rows]

    # ── Édition sélective ──────────────────────────────────────────

    def update_publisher_fields(self, publisher_id: int, fields: PublisherUpdate) -> None:
        data = fields.model_dump(exclude_unset=True)
        if data.get("name") is not None:
            data["name_normalized"] = normalize_text(data["name"])
        stmt = update(publishers).where(publishers.c.id == publisher_id).values(**data)
        result = self._conn.execute(stmt)
        if result.rowcount == 0:
            raise NotFoundError(f"Éditeur {publisher_id} introuvable")

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_publisher_into(self, target_id: int, source_id: int) -> None:
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

        # journal_name_forms : supprime d'abord les doublons avec target, puis transfère le reste.
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

        # Ordre : capture src → NULL-er openalex_id src (libère la contrainte UNIQUE) → enrich target → delete source.
        src = self._conn.execute(
            select(
                publishers.c.openalex_id,
                publishers.c.country,
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
                country=func.coalesce(publishers.c.country, src.country),
            )
        )

        self._conn.execute(delete(publishers).where(publishers.c.id == source_id))

        # pub_count : la cible a absorbé les revues de la source (les pub_count des revues sont inchangés) → recalcule la somme côté éditeur cible.
        refresh_publisher_pub_count(self._conn, target_id)
