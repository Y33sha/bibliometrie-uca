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
