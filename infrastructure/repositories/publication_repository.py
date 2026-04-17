"""Adapter PostgreSQL pour la persistance des publications.

Isole le SQL de la couche métier (services/publications.py). Même
contrat que PgPersonRepository : prend un curseur dans la transaction
courante, lève des exceptions du domaine quand pertinent.

Les namedtuples de résultat de recherche (PubByDoi, PubByNnt, …) sont
définies ici car c'est le repository qui les peuple ; elles sont
ré-exportées depuis services.publications pour ne pas casser les
call sites historiques.
"""

from collections import namedtuple

from utils.db_helpers import row_val as _val

# ── Types de résultat de recherche ─────────────────────────────────

PubByDoi = namedtuple("PubByDoi", ["id", "doc_type", "title_normalized"])
PubByNnt = namedtuple("PubByNnt", ["id", "doc_type", "title_normalized"])
PubByTitle = namedtuple("PubByTitle", ["id", "doi"])
PubThesisCandidate = namedtuple("PubThesisCandidate", ["id", "doi"])


class PgPublicationRepository:
    """Accès PostgreSQL à l'agrégat Publication."""

    def __init__(self, cur):
        self._cur = cur

    # ── Recherches ─────────────────────────────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None:
        """Cherche une publication par DOI (case-insensitive)."""
        if not doi:
            return None
        self._cur.execute(
            "SELECT id, doc_type, title_normalized FROM publications WHERE lower(doi) = lower(%s)",
            (doi,),
        )
        row = self._cur.fetchone()
        return PubByDoi(_val(row, 0), _val(row, 1), _val(row, 2)) if row else None

    def find_by_nnt(self, nnt: str) -> PubByNnt | None:
        """Cherche une publication via NNT stocké dans source_publications.external_ids."""
        if not nnt:
            return None
        self._cur.execute(
            """
            SELECT p.id, p.doc_type, p.title_normalized
            FROM publications p
            JOIN source_publications sd ON sd.publication_id = p.id
            WHERE sd.external_ids->>'nnt' = %s
            LIMIT 1
            """,
            (nnt.upper(),),
        )
        row = self._cur.fetchone()
        return PubByNnt(_val(row, 0), _val(row, 1), _val(row, 2)) if row else None

    def find_by_title(
        self, title_normalized: str, pub_year: int, journal_id: int,
    ) -> PubByTitle | None:
        """Cherche une publication par titre normalisé + année + journal.
        Ne matche que les articles avec journal connu."""
        if not title_normalized or not journal_id:
            return None
        self._cur.execute(
            """
            SELECT id, doi FROM publications
            WHERE title_normalized = %s AND pub_year = %s AND journal_id = %s
            LIMIT 1
            """,
            (title_normalized, pub_year, journal_id),
        )
        row = self._cur.fetchone()
        return PubByTitle(_val(row, 0), _val(row, 1)) if row else None

    def find_thesis_by_title(
        self, title_normalized: str, pub_year: int,
    ) -> list[PubThesisCandidate]:
        """Cherche des thèses par titre normalisé + année.

        Retourne les candidats pour déduplication thesis-specific
        (pas de journal_id, donc le tier 2 standard ne fonctionne pas).
        """
        if not title_normalized or not pub_year:
            return []
        self._cur.execute(
            """
            SELECT id, doi FROM publications
            WHERE title_normalized = %s AND pub_year = %s
              AND doc_type IN ('thesis', 'ongoing_thesis')
            ORDER BY id
            """,
            (title_normalized, pub_year),
        )
        rows = self._cur.fetchall()
        return [PubThesisCandidate(_val(row, 0), _val(row, 1)) for row in rows]

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None:
        """Met à jour le statut OA d'une publication."""
        self._cur.execute(
            """
            UPDATE publications SET oa_status = %s::oa_type, updated_at = now()
            WHERE id = %s
            """,
            (oa_status, pub_id),
        )

    def update_countries(self, pub_id: int, countries: list[str]) -> None:
        """Met à jour les pays d'une publication."""
        self._cur.execute(
            """
            UPDATE publications SET countries = %s, updated_at = now()
            WHERE id = %s
            """,
            (countries, pub_id),
        )

    def update_sources(self, pub_id: int) -> None:
        """Recalcule publications.sources depuis source_publications.

        Pas de lecture préalable : agrégation SQL directe en une requête.
        """
        self._cur.execute(
            """
            UPDATE publications SET sources = COALESCE(sub.srcs, '{}'), updated_at = now()
            FROM (
                SELECT array_agg(DISTINCT source::source_type ORDER BY source::source_type) AS srcs
                FROM source_publications
                WHERE publication_id = %s
            ) sub
            WHERE id = %s
            """,
            (pub_id, pub_id),
        )

    # ── Accès bas niveau au champ doi ──────────────────────────────

    def get_doi(self, pub_id: int) -> str | None:
        """Retourne le DOI courant d'une publication, ou None."""
        self._cur.execute("SELECT doi FROM publications WHERE id = %s", (pub_id,))
        row = self._cur.fetchone()
        if row is None:
            return None
        return row["doi"] if isinstance(row, dict) else row[0]

    def set_doi(self, pub_id: int, doi: str) -> None:
        """Attribue un DOI à une publication (ne vérifie pas les conflits
        d'unicité — le caller doit l'avoir fait via find_by_doi)."""
        self._cur.execute(
            "UPDATE publications SET doi = %s, updated_at = now() WHERE id = %s",
            (doi, pub_id),
        )

    def clear_doi(self, pub_id: int) -> None:
        """Retire le DOI d'une publication (utilisé lors des conflits
        chapitre/ouvrage)."""
        self._cur.execute(
            "UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s",
            (pub_id,),
        )

    # ── Création ───────────────────────────────────────────────────

    def create(
        self,
        *,
        title: str,
        title_normalized: str,
        doc_type: str,
        pub_year: int,
        doi: str | None,
        oa_status: str,
        journal_id: int | None,
        container_title: str | None,
        language: str | None,
    ) -> int:
        """Insère une publication et retourne son id.

        Le caller est responsable du tier de déduplication avant
        d'appeler `create` — le repo ne fait que le INSERT brut.
        """
        self._cur.execute(
            """
            INSERT INTO publications
                (title, title_normalized, doc_type, pub_year, doi,
                 oa_status, journal_id, container_title, language)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                title, title_normalized, doc_type, pub_year, doi,
                oa_status, journal_id, container_title, language,
            ),
        )
        return _val(self._cur.fetchone(), 0)

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(self, pub_id_a: int, pub_id_b: int) -> tuple[int, int] | None:
        """Marque deux publications comme distinctes. Idempotent.

        Retourne (a, b) si la paire vient d'être insérée, None sinon —
        le caller décide s'il émet un audit ou pas.
        """
        self._cur.execute(
            """
            INSERT INTO distinct_publications (pub_id_a, pub_id_b)
            VALUES (LEAST(%s, %s), GREATEST(%s, %s))
            ON CONFLICT DO NOTHING
            RETURNING pub_id_a, pub_id_b
            """,
            (pub_id_a, pub_id_b, pub_id_a, pub_id_b),
        )
        row = self._cur.fetchone()
        if not row:
            return None
        return row["pub_id_a"], row["pub_id_b"]
