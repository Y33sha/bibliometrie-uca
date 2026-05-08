"""Adapter PostgreSQL pour l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP).

Même contrat que les autres PgXxxRepository : exceptions du domaine,
pas d'orchestration métier (qui reste dans `application/journals.py`).

Mode dispatch (cur psycopg | Connection SA) pour cohabiter avec le
chantier sqlalchemy-core-adoption. La branche SA utilise la MetaData
explicite ; la branche psycopg conserve le code existant. Phase 4
supprimera la branche psycopg.
"""

from typing import Any

from sqlalchemy import Connection, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrastructure.db.tables import journal_name_forms, journals
from infrastructure.db_helpers import row_val as _val


class PgJournalRepository:
    """Accès PostgreSQL à l'agrégat Journal.

    Accepte un curseur psycopg ou une Connection SQLAlchemy.
    """

    def __init__(self, conn_or_cur: Any) -> None:
        self._conn = conn_or_cur
        self._is_sa = isinstance(conn_or_cur, Connection)

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
        if self._is_sa:
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
            return
        self._conn.execute(
            """
            INSERT INTO journal_name_forms (journal_id, form_normalized, publisher_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (form_normalized, publisher_id) DO NOTHING
            """,
            (journal_id, form_normalized, publisher_id),
        )

    def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        """Cherche un journal_id via une forme de nom normalisée,
        en privilégiant les journaux avec eISSN (plus fiable)."""
        if self._is_sa:
            stmt = (
                select(journal_name_forms.c.journal_id)
                .select_from(
                    journal_name_forms.join(
                        journals, journals.c.id == journal_name_forms.c.journal_id
                    )
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
            result = self._conn.execute(stmt)
            return result.scalar_one_or_none()
        self._conn.execute(
            """
            SELECT nf.journal_id FROM journal_name_forms nf
            JOIN journals j ON j.id = nf.journal_id
            WHERE nf.form_normalized = %s
              AND (nf.publisher_id IS NOT DISTINCT FROM %s::int
                   OR nf.publisher_id IS NULL OR %s::int IS NULL)
            ORDER BY (j.eissn IS NOT NULL) DESC, j.id ASC
            LIMIT 1
            """,
            (form_normalized, publisher_id, publisher_id),
        )
        row = self._conn.fetchone()
        return _val(row, 0) if row else None

    # ── journals ───────────────────────────────────────────────────

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None:
        """Cherche un journal par son openalex_id."""
        if self._is_sa:
            result = self._conn.execute(
                select(journals.c.id).where(journals.c.openalex_id == openalex_id)
            )
            return result.scalar_one_or_none()
        self._conn.execute(
            "SELECT id FROM journals WHERE openalex_id = %s",
            (openalex_id,),
        )
        row = self._conn.fetchone()
        return _val(row, 0) if row else None

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        """Cherche un journal dont l'un des 3 champs issn/eissn/issnl
        correspond à la valeur. Permet de chercher indifféremment par
        ISSN, eISSN ou ISSN-L."""
        if self._is_sa:
            result = self._conn.execute(
                select(journals.c.id)
                .where(
                    or_(
                        journals.c.issn == issn_value,
                        journals.c.eissn == issn_value,
                        journals.c.issnl == issn_value,
                    )
                )
                .limit(1)
            )
            return result.scalar_one_or_none()
        self._conn.execute(
            """
            SELECT id FROM journals
            WHERE issn = %s OR eissn = %s OR issnl = %s
            LIMIT 1
            """,
            (issn_value, issn_value, issn_value),
        )
        row = self._conn.fetchone()
        return _val(row, 0) if row else None

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
        if self._is_sa:
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
            return
        self._conn.execute(
            """
            UPDATE journals SET
                issn = COALESCE(journals.issn, %s),
                eissn = COALESCE(journals.eissn, %s),
                publisher_id = COALESCE(journals.publisher_id, %s),
                openalex_id = COALESCE(journals.openalex_id, %s),
                oa_model = COALESCE(journals.oa_model, %s)
            WHERE id = %s
            """,
            (issn, eissn, publisher_id, openalex_id, oa_model, journal_id),
        )

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
        if self._is_sa:
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
            result = self._conn.execute(stmt)
            return result.scalar_one()
        self._conn.execute(
            """
            INSERT INTO journals (title, title_normalized, issn, eissn, issnl,
                                  publisher_id, openalex_id, oa_model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, title_normalized, issn, eissn, issnl, publisher_id, openalex_id, oa_model),
        )
        return _val(self._conn.fetchone(), 0)

    # ── Updates génériques ─────────────────────────────────────────

    def journal_exists(self, journal_id: int) -> bool:
        """Vérifie l'existence d'un journal."""
        if self._is_sa:
            result = self._conn.execute(select(journals.c.id).where(journals.c.id == journal_id))
            return result.first() is not None
        self._conn.execute("SELECT id FROM journals WHERE id = %s", (journal_id,))
        return self._conn.fetchone() is not None

    def update_journal_fields(self, journal_id: int, fields: dict) -> None:
        """UPDATE dynamique sur journals. Pas de validation ici (l'existence
        et la non-vacuité des fields sont vérifiées par le service)."""
        if self._is_sa:
            stmt = (
                update(journals)
                .where(journals.c.id == journal_id)
                .values(**fields, updated_at=func.now())
            )
            self._conn.execute(stmt)
            return
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._conn.execute(
            f"UPDATE journals SET {sets}, updated_at = now() WHERE id = %s",
            list(fields.values()) + [journal_id],
        )

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
        if self._is_sa:
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
            return
        self._conn.execute(
            """
            UPDATE journals SET
                apc_amount = COALESCE(%s, journals.apc_amount),
                apc_currency = COALESCE(%s, journals.apc_currency),
                is_in_doaj = COALESCE(%s, journals.is_in_doaj)
            WHERE id = %s
            """,
            (apc_amount, apc_currency, is_in_doaj, journal_id),
        )

    def reset_journal_apc(self) -> int:
        """Réinitialise les APC/DOAJ de toutes les revues avec openalex_id.
        Retourne le nombre de lignes touchées."""
        if self._is_sa:
            stmt = (
                update(journals)
                .where(journals.c.openalex_id.is_not(None))
                .values(apc_amount=None, apc_currency="EUR", is_in_doaj=False)
            )
            result = self._conn.execute(stmt)
            return result.rowcount
        self._conn.execute("""
            UPDATE journals
            SET apc_amount = NULL, apc_currency = 'EUR', is_in_doaj = FALSE
            WHERE openalex_id IS NOT NULL
        """)
        return self._conn.rowcount

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
        if self._is_sa:
            jt = journals.alias("jt")
            js = journals.alias("js")
            stmt = (
                select(
                    jt.c.id.label("target_journal_id"),
                    js.c.id.label("source_journal_id"),
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
            result = self._conn.execute(stmt)
            return [dict(r._mapping) for r in result]
        self._conn.execute(
            """
            SELECT
                jt.id  AS target_journal_id,
                js.id  AS source_journal_id,
                jt.issn  AS t_issn,  jt.eissn AS t_eissn, jt.issnl AS t_issnl,
                js.issn  AS s_issn,  js.eissn AS s_eissn, js.issnl AS s_issnl
            FROM journals jt
            JOIN journals js ON js.title_normalized = jt.title_normalized
            WHERE jt.publisher_id = %s AND js.publisher_id = %s
            """,
            (target_publisher_id, source_publisher_id),
        )
        return self._conn.fetchall()

    def merge_journal_into(self, target_id: int, source_id: int) -> None:
        """Fusion de journal (5 étapes SQL) :
        1. Transfert des publications et source_publications
        2. Transfert/dédup des journal_name_forms
        3. Transfert des apc_payments
        4. Enrichissement COALESCE des métadonnées journal
        5. Suppression de la source
        """
        if self._is_sa:
            # 1. Transférer les publications et source_publications (cross-aggregate :
            #    on touche d'autres tables sans avoir migré leur MetaData ; SQL brut
            #    via text() — pattern documenté dans la fiche).
            self._conn.execute(
                text("UPDATE publications SET journal_id = :t WHERE journal_id = :s"),
                {"t": target_id, "s": source_id},
            )
            self._conn.execute(
                text("UPDATE source_publications SET journal_id = :t WHERE journal_id = :s"),
                {"t": target_id, "s": source_id},
            )

            # 2. Transférer les journal_name_forms (anti-doublon)
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

            # 3. Transférer les apc_payments (cross-aggregate)
            self._conn.execute(
                text("UPDATE apc_payments SET journal_id = :t WHERE journal_id = :s"),
                {"t": target_id, "s": source_id},
            )

            # 4. Enrichir la cible depuis la source (SELECT puis UPDATE pour
            # éviter le warning "cartesian product" sur UPDATE…FROM côté SA).
            src_result = self._conn.execute(
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
            )
            src = src_result.one()
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

            # 5. Supprimer la source
            self._conn.execute(delete(journals).where(journals.c.id == source_id))
            return

        # 1. Transférer les publications et source_publications
        self._conn.execute(
            "UPDATE publications SET journal_id = %s WHERE journal_id = %s",
            (target_id, source_id),
        )
        self._conn.execute(
            "UPDATE source_publications SET journal_id = %s WHERE journal_id = %s",
            (target_id, source_id),
        )

        # 2. Transférer les journal_name_forms (dédup par (form_normalized,
        # publisher_id) en traitant NULL comme 0 pour l'uniqueness)
        self._conn.execute(
            """
            UPDATE journal_name_forms SET journal_id = %s
            WHERE journal_id = %s
              AND (form_normalized, COALESCE(publisher_id, 0)) NOT IN (
                  SELECT form_normalized, COALESCE(publisher_id, 0)
                  FROM journal_name_forms WHERE journal_id = %s
              )
            """,
            (target_id, source_id, target_id),
        )
        self._conn.execute(
            "DELETE FROM journal_name_forms WHERE journal_id = %s",
            (source_id,),
        )

        # 3. Transférer les apc_payments
        self._conn.execute(
            "UPDATE apc_payments SET journal_id = %s WHERE journal_id = %s",
            (target_id, source_id),
        )

        # 4. Enrichir la cible (COALESCE sur toutes les métadonnées)
        self._conn.execute(
            """
            UPDATE journals dest SET
                issn = COALESCE(dest.issn, src.issn),
                eissn = COALESCE(dest.eissn, src.eissn),
                issnl = COALESCE(dest.issnl, src.issnl),
                publisher_id = COALESCE(dest.publisher_id, src.publisher_id),
                openalex_id = COALESCE(dest.openalex_id, src.openalex_id),
                is_in_doaj = dest.is_in_doaj OR src.is_in_doaj,
                is_predatory = dest.is_predatory OR src.is_predatory,
                apc_amount = COALESCE(dest.apc_amount, src.apc_amount),
                apc_currency = COALESCE(dest.apc_currency, src.apc_currency),
                oa_model = COALESCE(dest.oa_model, src.oa_model),
                updated_at = now()
            FROM journals src
            WHERE dest.id = %s AND src.id = %s
            """,
            (target_id, source_id),
        )

        # 5. Supprimer la source
        self._conn.execute("DELETE FROM journals WHERE id = %s", (source_id,))
