"""Adapter PostgreSQL de la table `journals` pour le pipeline.

Sert les trois contrats pipeline (`application/ports/pipeline/journals.py`) : trouve-ou-crée d'une revue à partir des sources, enrichissement OpenAlex (typage + APC) et import du dump DOAJ. La table étant mono-adapter, une seule classe implémente les trois Protocols. L'édition curée et la fusion (admin) vivent dans `infrastructure/repositories/journal_repository.py`.
"""

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import Connection, case, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.pipeline.journals import (
    JournalDoajQueries,
    JournalFindOrCreateQueries,
    JournalIssnRow,
    JournalOpenAlexEnrichmentQueries,
)
from domain.journals.journal import JournalType, OaModel
from domain.normalize import normalize_text
from domain.types import JsonValue
from infrastructure.db.tables import journal_name_forms, journals


class PgJournalGatewayQueries(
    JournalFindOrCreateQueries, JournalOpenAlexEnrichmentQueries, JournalDoajQueries
):
    """Accès PostgreSQL à `journals` pour le pipeline, via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── journal_name_forms ─────────────────────────────────────────

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
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
        return self._conn.execute(
            select(journals.c.id).where(journals.c.openalex_id == openalex_id)
        ).scalar_one_or_none()

    def find_journals_of_unknown_type(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        rows = self._conn.execute(
            select(journals.c.id, journals.c.openalex_id)
            .where(journals.c.openalex_id.is_not(None))
            .where(journals.c.journal_type == "unknown")
            .order_by(journals.c.id)
            .limit(limit or None)
        ).all()
        return [(r.id, r.openalex_id) for r in rows]

    def find_journal_issn_index(self) -> list[JournalIssnRow]:
        return [
            JournalIssnRow(r.id, r.issn, r.eissn, r.issnl)
            for r in self._conn.execute(
                select(journals.c.id, journals.c.issn, journals.c.eissn, journals.c.issnl).where(
                    or_(
                        journals.c.issn.is_not(None),
                        journals.c.eissn.is_not(None),
                        journals.c.issnl.is_not(None),
                    )
                )
            ).all()
        ]

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
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
        oa_model: OaModel | None = None,
    ) -> None:
        # L'UPDATE n'est émis que si au moins une colonne NULL recevrait une valeur.
        fillable = (
            (journals.c.issn, issn),
            (journals.c.eissn, eissn),
            (journals.c.publisher_id, publisher_id),
            (journals.c.openalex_id, openalex_id),
            (journals.c.oa_model, oa_model),
        )
        null_targets = [col.is_(None) for col, value in fillable if value is not None]
        if not null_targets:
            return
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id, or_(*null_targets))
            .values(
                issn=func.coalesce(journals.c.issn, issn),
                eissn=func.coalesce(journals.c.eissn, eissn),
                publisher_id=func.coalesce(journals.c.publisher_id, publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, openalex_id),
                # Le littéral est lié au type de la colonne : `coalesce` ne le lui emprunte pas, et
                # `oa_model` est une enum, qu'un paramètre texte ne rejoint pas.
                oa_model=func.coalesce(
                    journals.c.oa_model, literal(oa_model, journals.c.oa_model.type)
                ),
            )
        )
        self._conn.execute(stmt)

    def create_journal(
        self,
        *,
        title: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: OaModel | None,
    ) -> int:
        """Insère un journal et retourne son id. `title_normalized` est dérivé de `title`."""
        stmt = (
            journals.insert()
            .values(
                title=title,
                title_normalized=normalize_text(title),
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

    # ── Enrichissement OpenAlex ────────────────────────────────────

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
    ) -> None:
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                apc_amount=func.coalesce(apc_amount, journals.c.apc_amount),
                apc_currency=func.coalesce(apc_currency, journals.c.apc_currency),
            )
        )
        self._conn.execute(stmt)

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        self._conn.execute(
            update(journals).where(journals.c.id == journal_id).values(journal_type=journal_type)
        )

    # ── Import DOAJ ────────────────────────────────────────────────

    def update_journal_doaj(
        self,
        journal_id: int,
        *,
        payload: Mapping[str, JsonValue] | None,
        imported_at: datetime,
        is_in_doaj: bool,
    ) -> None:
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                doaj_payload=payload,
                doaj_imported_at=imported_at,
                is_in_doaj=is_in_doaj,
            )
        )
        self._conn.execute(stmt)

    def reset_is_in_doaj(self) -> int:
        return self._conn.execute(
            update(journals).where(journals.c.is_in_doaj).values(is_in_doaj=False)
        ).rowcount

    def doaj_last_import_at(self) -> datetime | None:
        return self._conn.execute(select(func.max(journals.c.doaj_imported_at))).scalar_one()
