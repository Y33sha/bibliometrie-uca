"""Adapter PostgreSQL pour l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP).

Même contrat que les autres PgXxxRepository : curseur dans la
transaction courante, exceptions du domaine, pas d'orchestration
métier (qui reste dans `application/journals.py`).
"""

from typing import Any

from infrastructure.db_helpers import row_val as _val


class PgJournalRepository:
    """Accès PostgreSQL à l'agrégat Journal."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

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
        self._cur.execute(
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
        self._cur.execute(
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
        row = self._cur.fetchone()
        return _val(row, 0) if row else None

    # ── journals ───────────────────────────────────────────────────

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None:
        """Cherche un journal par son openalex_id."""
        self._cur.execute(
            "SELECT id FROM journals WHERE openalex_id = %s",
            (openalex_id,),
        )
        row = self._cur.fetchone()
        return _val(row, 0) if row else None

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        """Cherche un journal dont l'un des 3 champs issn/eissn/issnl
        correspond à la valeur. Permet de chercher indifféremment par
        ISSN, eISSN ou ISSN-L."""
        self._cur.execute(
            """
            SELECT id FROM journals
            WHERE issn = %s OR eissn = %s OR issnl = %s
            LIMIT 1
            """,
            (issn_value, issn_value, issn_value),
        )
        row = self._cur.fetchone()
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
        self._cur.execute(
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
        self._cur.execute(
            """
            INSERT INTO journals (title, title_normalized, issn, eissn, issnl,
                                  publisher_id, openalex_id, oa_model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, title_normalized, issn, eissn, issnl, publisher_id, openalex_id, oa_model),
        )
        return _val(self._cur.fetchone(), 0)

    # ── Updates génériques ─────────────────────────────────────────

    def journal_exists(self, journal_id: int) -> bool:
        """Vérifie l'existence d'un journal."""
        self._cur.execute("SELECT id FROM journals WHERE id = %s", (journal_id,))
        return self._cur.fetchone() is not None

    def update_journal_fields(self, journal_id: int, fields: dict) -> None:
        """UPDATE dynamique sur journals. Pas de validation ici (l'existence
        et la non-vacuité des fields sont vérifiées par le service)."""
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._cur.execute(
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
        self._cur.execute(
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
        self._cur.execute("""
            UPDATE journals
            SET apc_amount = NULL, apc_currency = 'EUR', is_in_doaj = FALSE
            WHERE openalex_id IS NOT NULL
        """)
        return self._cur.rowcount

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
        self._cur.execute(
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
        return self._cur.fetchall()

    def merge_journal_into(self, target_id: int, source_id: int) -> None:
        """Fusion de journal (5 étapes SQL) :
        1. Transfert des publications et source_publications
        2. Transfert/dédup des journal_name_forms
        3. Transfert des apc_payments
        4. Enrichissement COALESCE des métadonnées journal
        5. Suppression de la source
        """
        # 1. Transférer les publications et source_publications
        self._cur.execute(
            "UPDATE publications SET journal_id = %s WHERE journal_id = %s",
            (target_id, source_id),
        )
        self._cur.execute(
            "UPDATE source_publications SET journal_id = %s WHERE journal_id = %s",
            (target_id, source_id),
        )

        # 2. Transférer les journal_name_forms (dédup par (form_normalized,
        # publisher_id) en traitant NULL comme 0 pour l'uniqueness)
        self._cur.execute(
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
        self._cur.execute(
            "DELETE FROM journal_name_forms WHERE journal_id = %s",
            (source_id,),
        )

        # 3. Transférer les apc_payments
        self._cur.execute(
            "UPDATE apc_payments SET journal_id = %s WHERE journal_id = %s",
            (target_id, source_id),
        )

        # 4. Enrichir la cible (COALESCE sur toutes les métadonnées)
        self._cur.execute(
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
        self._cur.execute("DELETE FROM journals WHERE id = %s", (source_id,))
