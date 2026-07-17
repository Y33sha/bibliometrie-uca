"""Adapter PostgreSQL pour l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP).

Même contrat que les autres PgXxxRepository : exceptions du domaine,
pas d'orchestration métier (qui reste dans `application/journals.py`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, NamedTuple, cast

from sqlalchemy import Connection, case, delete, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.journal_repository import JournalIssnRow, JournalUpdate
from domain.errors import NotFoundError
from domain.journals.journal import Journal, JournalType, OaModel
from domain.normalize import normalize_text
from infrastructure.db.tables import journal_name_forms, journals
from infrastructure.queries.pipeline.pub_counts import (
    refresh_journal_pub_count,
    refresh_publisher_pub_count,
)


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
    apc_amount: Decimal | None
    apc_currency: str | None
    oa_model: str | None
    journal_type: str | None
    is_academic: bool | None
    doi_prefix: str | None


def _journal_from_row(row: _JournalRow) -> Journal:
    """Mappe une row `journals` SQL vers l'aggregate `Journal`.

    Coerce les valeurs vers les types du domaine : `journal_type` et `is_academic`, nullables au schéma, retombent sur leur défaut (`unknown` / `True`). Les enums SQL `journal_type` et `oa_model` reprennent le vocabulaire du domaine, d'où la simple assertion de type.
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
        apc_amount=row.apc_amount,
        apc_currency=row.apc_currency,
        oa_model=cast(OaModel | None, row.oa_model),
        journal_type=cast(JournalType, row.journal_type)
        if row.journal_type is not None
        else "unknown",
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

    def find_journals_of_unknown_type(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des revues à typer via OpenAlex.

        Filtre : `openalex_id` renseigné ET `journal_type = 'unknown'`. Le type est stable par revue : une revue créée naît `unknown` (défaut DB), est typée au passage, puis sort de la file. L'APC est extrait opportunistement dans la même réponse OpenAlex.
        """
        rows = self._conn.execute(
            select(journals.c.id, journals.c.openalex_id)
            .where(journals.c.openalex_id.is_not(None))
            .where(journals.c.journal_type == "unknown")
            .order_by(journals.c.id)
            .limit(limit or None)
        ).all()
        return [(r.id, r.openalex_id) for r in rows]

    def find_journal_issn_index(self) -> list[JournalIssnRow]:
        """Les revues portant au moins un ISSN, sous l'une des trois formes."""
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
        oa_model: OaModel | None = None,
    ) -> None:
        """Enrichit un journal existant avec les champs non null fournis
        (COALESCE sur chaque champ : ne downgrade jamais).

        Garde anti-bloat : l'UPDATE n'est émis que si au moins une colonne
        actuellement NULL recevrait une valeur. Sans ce filtre, chaque match de
        journal (fréquent — un journal populaire est partagé par des milliers de
        publis) réécrivait la ligne inutilement (COALESCE vers la même valeur),
        générant un tuple mort à chaque appel → bloat de `journals` et lookups
        de plus en plus lents au fil du run normalize.
        """
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

    # ── Updates génériques ─────────────────────────────────────────

    def update_journal_fields(self, journal_id: int, fields: JournalUpdate) -> None:
        """UPDATE dynamique sur journals à partir des champs fournis, `title_normalized` dérivé de `title` quand il est présent.

        L'`UPDATE` rapporte les lignes appariées : zéro dit l'absence, sans lecture préalable. La non-vacuité des champs est vérifiée par le service.
        """
        data = fields.model_dump(exclude_unset=True)
        if data.get("title") is not None:
            data["title_normalized"] = normalize_text(data["title"])
        stmt = update(journals).where(journals.c.id == journal_id).values(**data)
        result = self._conn.execute(stmt)
        if result.rowcount == 0:
            raise NotFoundError(f"Revue {journal_id} introuvable")

    # ── APC / DOAJ ─────────────────────────────────────────────────

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
    ) -> None:
        """Met à jour les infos APC (COALESCE : champs None ignorés)."""
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                apc_amount=func.coalesce(apc_amount, journals.c.apc_amount),
                apc_currency=func.coalesce(apc_currency, journals.c.apc_currency),
            )
        )
        self._conn.execute(stmt)

    def update_journal_doaj(
        self,
        journal_id: int,
        *,
        payload: dict[str, Any] | None,
        imported_at: datetime,
        is_in_doaj: bool,
    ) -> None:
        """Pose `doaj_payload`/`doaj_imported_at`/`is_in_doaj` en bloc."""
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
        """Efface le drapeau `is_in_doaj` des revues qui le portent.

        Le `WHERE is_in_doaj` donne un rowcount juste et épargne des dead tuples : sans lui, l'UPDATE réécrirait toute la table.
        """
        return self._conn.execute(
            update(journals).where(journals.c.is_in_doaj).values(is_in_doaj=False)
        ).rowcount

    def doaj_last_import_at(self) -> datetime | None:
        """Date du dernier import DOAJ, `None` si jamais importé."""
        return self._conn.execute(select(func.max(journals.c.doaj_imported_at))).scalar_one()

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
        """Fusion de journal (une transaction) :
        1. Transfert des publications et source_publications
        2. Transfert/dédup des journal_name_forms
        3. Transfert des apc_payments
        4. Suppression de la source
        5. Enrichissement COALESCE de la cible depuis les valeurs capturées de la source

        La source est supprimée avant l'enrichissement : la cible reprend alors son `openalex_id` (COALESCE) sans buter sur la contrainte `UNIQUE`, l'enrichissement lisant des valeurs déjà capturées.

        Les UPDATEs cross-agrégat (publications, source_publications, apc_payments) restent en `text()` : leurs tables ne sont pas dans la MetaData côté `infrastructure/db/tables.py` (gérées par leurs propres repos).
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

        # Capture des métadonnées de la source, puis suppression de la source avant l'enrichissement : la cible reprend ensuite ses valeurs (COALESCE) sans conflit sur `UNIQUE(openalex_id)`.
        src = self._conn.execute(
            select(
                journals.c.issn,
                journals.c.eissn,
                journals.c.issnl,
                journals.c.publisher_id,
                journals.c.openalex_id,
                journals.c.is_in_doaj,
                journals.c.apc_amount,
                journals.c.apc_currency,
                journals.c.oa_model,
            ).where(journals.c.id == source_id)
        ).one()
        self._conn.execute(delete(journals).where(journals.c.id == source_id))
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
                apc_amount=func.coalesce(journals.c.apc_amount, src.apc_amount),
                apc_currency=func.coalesce(journals.c.apc_currency, src.apc_currency),
                oa_model=func.coalesce(journals.c.oa_model, src.oa_model),
            )
        )

        # pub_count : la cible a absorbé les publications de la source. Recalcule la
        # revue cible, puis les éditeurs concernés (cible + ancien éditeur source).
        refresh_journal_pub_count(self._conn, target_id)
        target_publisher = self._conn.execute(
            select(journals.c.publisher_id).where(journals.c.id == target_id)
        ).scalar()
        for publisher_id in {target_publisher, src.publisher_id} - {None}:
            refresh_publisher_pub_count(self._conn, publisher_id)
