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

    # ── journal_name_forms ─────────────────────────────────────────

    def add_journal_name_form(
        self, journal_id: int, form_normalized: str, publisher_id: int | None,
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
        self, form_normalized: str, publisher_id: int | None,
    ) -> int | None:
        """Cherche un journal_id via une forme de nom normalisée,
        en privilégiant les journaux avec eISSN (plus fiable)."""
        self._cur.execute(
            """
            SELECT nf.journal_id FROM journal_name_forms nf
            JOIN journals j ON j.id = nf.journal_id
            WHERE nf.form_normalized = %s
              AND (nf.publisher_id IS NOT DISTINCT FROM %s
                   OR nf.publisher_id IS NULL OR %s IS NULL)
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
            (title, title_normalized, issn, eissn, issnl,
             publisher_id, openalex_id, oa_model),
        )
        return _val(self._cur.fetchone(), 0)

    # ── Updates génériques ─────────────────────────────────────────

    def journal_exists(self, journal_id: int) -> bool:
        """Vérifie l'existence d'un journal."""
        self._cur.execute("SELECT id FROM journals WHERE id = %s", (journal_id,))
        return self._cur.fetchone() is not None

    def publisher_exists(self, publisher_id: int) -> bool:
        """Vérifie l'existence d'un publisher."""
        self._cur.execute("SELECT id FROM publishers WHERE id = %s", (publisher_id,))
        return self._cur.fetchone() is not None

    def update_journal_fields(self, journal_id: int, fields: dict) -> None:
        """UPDATE dynamique sur journals. Pas de validation ici (l'existence
        et la non-vacuité des fields sont vérifiées par le service)."""
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._cur.execute(
            f"UPDATE journals SET {sets}, updated_at = now() WHERE id = %s",
            list(fields.values()) + [journal_id],
        )

    def update_publisher_fields(self, publisher_id: int, fields: dict) -> None:
        """UPDATE dynamique sur publishers."""
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._cur.execute(
            f"UPDATE publishers SET {sets}, updated_at = now() WHERE id = %s",
            list(fields.values()) + [publisher_id],
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
