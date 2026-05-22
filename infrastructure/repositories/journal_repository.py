"""Adapter PostgreSQL pour l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP).

Même contrat que les autres PgXxxRepository : exceptions du domaine,
pas d'orchestration métier (qui reste dans `application/journals.py`).
"""

from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import Connection, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.journal_repository import JournalUpdateFields
from domain.journals.journal import Journal
from infrastructure.db.tables import journal_name_forms, journals


class _JournalRow(NamedTuple):
    """Projection SQL `find_by_id` sur `journals`."""

    id: int
    title: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    publisher_id: int | None
    openalex_id: str | None
    is_in_doaj: bool
    is_predatory: bool
    apc_amount: Decimal | None
    apc_currency: str | None
    oa_model: str | None
    journal_type: str | None
    is_academic: bool | None
    doi_prefix: str | None


def _journal_from_row(row: _JournalRow) -> Journal:
    """Mapping d'une row `journals` SQL vers l'aggregate `Journal`.

    `journal_type` et `is_academic` ont des DEFAULT côté DB ('journal' / true) mais leur colonne reste nullable au schéma — on coerce vers le default pour préserver la sémantique non-nullable de l'aggregate.
    """
    return Journal(
        id=row.id,
        title=row.title,
        issn=row.issn,
        eissn=row.eissn,
        issnl=row.issnl,
        publisher_id=row.publisher_id,
        openalex_id=row.openalex_id,
        is_in_doaj=row.is_in_doaj,
        is_predatory=row.is_predatory,
        apc_amount=row.apc_amount,
        apc_currency=row.apc_currency,
        oa_model=row.oa_model,
        journal_type=row.journal_type if row.journal_type is not None else "journal",
        is_academic=row.is_academic if row.is_academic is not None else True,
        doi_prefix=row.doi_prefix,
    )


class PgJournalRepository:
    """Accès PostgreSQL à l'agrégat Journal via une `Connection` SA."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, journal_id: int) -> Journal | None:
        row = self._conn.execute(
            select(
                journals.c.id,
                journals.c.title,
                journals.c.issn,
                journals.c.eissn,
                journals.c.issnl,
                journals.c.publisher_id,
                journals.c.openalex_id,
                journals.c.is_in_doaj,
                journals.c.is_predatory,
                journals.c.apc_amount,
                journals.c.apc_currency,
                journals.c.oa_model,
                journals.c.journal_type,
                journals.c.is_academic,
                journals.c.doi_prefix,
            ).where(journals.c.id == journal_id)
        ).first()
        if row is None:
            return None
        return _journal_from_row(_JournalRow(*row))

    # ── journal_name_forms ─────────────────────────────────────────

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
        """Ajoute une forme de nom de journal si elle n'existe pas (idempotent).
        No-op si form_normalized est vide."""
        if not form_normalized:
            return
        stmt = (
            pg_insert(journal_name_forms)
            .values(
                journal_id=journal_id,
                form_normalized=form_normalized,
                publisher_id=publisher_id,
            )
            .on_conflict_do_nothing(index_elements=["form_normalized", "publisher_id"])
        )
        self._conn.execute(stmt)

    def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        """Cherche un journal_id via une forme de nom normalisée,
        en privilégiant les journaux avec eISSN (plus fiable)."""
        stmt = (
            select(journal_name_forms.c.journal_id)
            .select_from(
                journal_name_forms.join(journals, journals.c.id == journal_name_forms.c.journal_id)
            )
            .where(journal_name_forms.c.form_normalized == form_normalized)
            .order_by(
                case((journals.c.eissn.is_not(None), 1), else_=0).desc(),
                journals.c.id.asc(),
            )
            .limit(1)
        )
        if publisher_id is not None:
            stmt = stmt.where(
                or_(
                    journal_name_forms.c.publisher_id == publisher_id,
                    journal_name_forms.c.publisher_id.is_(None),
                )
            )
        return self._conn.execute(stmt).scalar_one_or_none()

    # ── journals ───────────────────────────────────────────────────

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None:
        """Cherche un journal par son openalex_id."""
        return self._conn.execute(
            select(journals.c.id).where(journals.c.openalex_id == openalex_id)
        ).scalar_one_or_none()

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        """Cherche un journal dont l'un des 3 champs issn/eissn/issnl
        correspond à la valeur. Permet de chercher indifféremment par
        ISSN, eISSN ou ISSN-L."""
        return self._conn.execute(
            select(journals.c.id)
            .where(
                or_(
                    journals.c.issn == issn_value,
                    journals.c.eissn == issn_value,
                    journals.c.issnl == issn_value,
                )
            )
            .limit(1)
        ).scalar_one_or_none()

    def enrich_journal(
        self,
        journal_id: int,
        *,
        issn: str | None = None,
        eissn: str | None = None,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: str | None = None,
    ) -> None:
        """Enrichit un journal existant avec les champs non null fournis
        (COALESCE sur chaque champ : ne downgrade jamais)."""
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                issn=func.coalesce(journals.c.issn, issn),
                eissn=func.coalesce(journals.c.eissn, eissn),
                publisher_id=func.coalesce(journals.c.publisher_id, publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, openalex_id),
                oa_model=func.coalesce(journals.c.oa_model, oa_model),
            )
        )
        self._conn.execute(stmt)

    def create_journal(
        self,
        *,
        title: str,
        title_normalized: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: str | None,
    ) -> int:
        """Insère un journal et retourne son id."""
        stmt = (
            journals.insert()
            .values(
                title=title,
                title_normalized=title_normalized,
                issn=issn,
                eissn=eissn,
                issnl=issnl,
                publisher_id=publisher_id,
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            .returning(journals.c.id)
        )
        return self._conn.execute(stmt).scalar_one()

    # ── Updates génériques ─────────────────────────────────────────

    def journal_exists(self, journal_id: int) -> bool:
        """Vérifie l'existence d'un journal."""
        return (
            self._conn.execute(select(journals.c.id).where(journals.c.id == journal_id)).first()
            is not None
        )

    def update_journal_fields(self, journal_id: int, fields: JournalUpdateFields) -> None:
        """UPDATE dynamique sur journals. Pas de validation ici (l'existence
        et la non-vacuité des fields sont vérifiées par le service)."""
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(**fields, updated_at=func.now())
        )
        self._conn.execute(stmt)

    # ── APC / DOAJ ─────────────────────────────────────────────────

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
        is_in_doaj: bool | None = None,
    ) -> None:
        """Met à jour les infos APC/DOAJ (COALESCE : champs None ignorés)."""
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                apc_amount=func.coalesce(apc_amount, journals.c.apc_amount),
                apc_currency=func.coalesce(apc_currency, journals.c.apc_currency),
                is_in_doaj=func.coalesce(is_in_doaj, journals.c.is_in_doaj),
            )
        )
        self._conn.execute(stmt)

    def reset_journal_apc(self) -> int:
        """Réinitialise les APC/DOAJ de toutes les revues avec openalex_id.
        Retourne le nombre de lignes touchées."""
        stmt = (
            update(journals)
            .where(journals.c.openalex_id.is_not(None))
            .values(apc_amount=None, apc_currency="EUR", is_in_doaj=False)
        )
        return self._conn.execute(stmt).rowcount

    # ── Fusion ─────────────────────────────────────────────────────

    def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[dict]:
        """Retourne les paires de journaux (un du target, un du source)
        qui partagent le même `title_normalized`.

        Chaque ligne contient `target_journal_id`, `source_journal_id`,
        et les 6 valeurs ISSN/eISSN/ISSN-L des deux côtés — tout est
        récupéré en une seule requête pour permettre au service de
        détecter les conflits ISSN sans SELECT additionnel.
        """
        jt = journals.alias("jt")
        js = journals.alias("js")
        stmt = (
            select(
                jt.c.id.label("target_journal_id"),
                js.c.id.label("source_journal_id"),
                jt.c.title.label("t_title"),
                js.c.title.label("s_title"),
                jt.c.issn.label("t_issn"),
                jt.c.eissn.label("t_eissn"),
                jt.c.issnl.label("t_issnl"),
                js.c.issn.label("s_issn"),
                js.c.eissn.label("s_eissn"),
                js.c.issnl.label("s_issnl"),
            )
            .select_from(jt.join(js, js.c.title_normalized == jt.c.title_normalized))
            .where(jt.c.publisher_id == target_publisher_id)
            .where(js.c.publisher_id == source_publisher_id)
        )
        return [dict(r._mapping) for r in self._conn.execute(stmt)]

    def merge_journal_into(self, target_id: int, source_id: int) -> None:
        """Fusion de journal (5 étapes SQL) :
        1. Transfert des publications et source_publications
        2. Transfert/dédup des journal_name_forms
        3. Transfert des apc_payments
        4. Enrichissement COALESCE des métadonnées journal
        5. Suppression de la source

        Les UPDATEs cross-agrégat (publications, source_publications,
        apc_payments) restent en `text()` : leurs tables ne sont pas dans
        la MetaData côté `infrastructure/db/tables.py` (volontairement —
        elles sont gérées par leurs propres repos).
        """
        self._conn.execute(
            text("UPDATE publications SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )
        self._conn.execute(
            text("UPDATE source_publications SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # journal_name_forms (anti-doublon) : forme/publisher commun → on garde la cible.
        self._conn.execute(
            text("""
                UPDATE journal_name_forms SET journal_id = :t
                WHERE journal_id = :s
                  AND (form_normalized, COALESCE(publisher_id, 0)) NOT IN (
                      SELECT form_normalized, COALESCE(publisher_id, 0)
                      FROM journal_name_forms WHERE journal_id = :t
                  )
            """),
            {"t": target_id, "s": source_id},
        )
        self._conn.execute(
            delete(journal_name_forms).where(journal_name_forms.c.journal_id == source_id)
        )

        self._conn.execute(
            text("UPDATE apc_payments SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # Ordre : capture src → NULL-er openalex_id src (libère la contrainte
        # UNIQUE) → enrich target → delete source. Sans ce NULL préalable,
        # COALESCE essaie de coller openalex_id source sur target alors que
        # source l'a encore → UniqueViolation.
        src = self._conn.execute(
            select(
                journals.c.issn,
                journals.c.eissn,
                journals.c.issnl,
                journals.c.publisher_id,
                journals.c.openalex_id,
                journals.c.is_in_doaj,
                journals.c.is_predatory,
                journals.c.apc_amount,
                journals.c.apc_currency,
                journals.c.oa_model,
            ).where(journals.c.id == source_id)
        ).one()
        self._conn.execute(
            update(journals).where(journals.c.id == source_id).values(openalex_id=None)
        )
        self._conn.execute(
            update(journals)
            .where(journals.c.id == target_id)
            .values(
                issn=func.coalesce(journals.c.issn, src.issn),
                eissn=func.coalesce(journals.c.eissn, src.eissn),
                issnl=func.coalesce(journals.c.issnl, src.issnl),
                publisher_id=func.coalesce(journals.c.publisher_id, src.publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, src.openalex_id),
                is_in_doaj=journals.c.is_in_doaj | src.is_in_doaj,
                is_predatory=journals.c.is_predatory | src.is_predatory,
                apc_amount=func.coalesce(journals.c.apc_amount, src.apc_amount),
                apc_currency=func.coalesce(journals.c.apc_currency, src.apc_currency),
                oa_model=func.coalesce(journals.c.oa_model, src.oa_model),
                updated_at=func.now(),
            )
        )

        self._conn.execute(delete(journals).where(journals.c.id == source_id))
