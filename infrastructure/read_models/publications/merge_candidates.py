"""Candidats à la fusion manuelle avec une publication : titres proches, ou recherche par identifiant, DOI ou titre."""

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.publications.identifiers import DOI
from infrastructure.read_models.publications.models import MergeCandidateOut

_LIMIT = 10


def _candidates_sql(similarity: str, condition: str, *, ranked: bool = False) -> str:
    """Renvoie la requête des publications fusionnables avec `:publication` et satisfaisant `condition`.

    Une publication de DOI différent de celui de `:publication` est écartée : la fusion la refuserait.

    Args:
        similarity: expression de la similarité renvoyée.
        ranked: tri par similarité décroissante, puis par écart d'année.
    """
    order = (
        f"ORDER BY similarity DESC, abs(c.publication_year - p.publication_year), c.id LIMIT {_LIMIT}"
        if ranked
        else ""
    )
    return f"""
        SELECT c.id, c.title, c.publication_year, c.doc_type::text AS doc_type, c.doi,
               {similarity} AS similarity,
               ARRAY(SELECT DISTINCT sr.source::text FROM source_records sr
                     WHERE sr.publication_id = c.id ORDER BY 1) AS sources
        FROM publications c
        JOIN publications p ON p.id = :publication
        WHERE c.id <> p.id
          AND (c.doi IS NULL OR p.doi IS NULL OR lower(c.doi) = lower(p.doi))
          AND {condition}
        {order}
    """  # noqa: S608


_TITLE_SIMILARITY = "similarity(c.title_normalized, :title)"

# Les opérateurs `%` (titre proche du titre de référence) et `<%` (mots de la saisie présents dans le titre) appliquent les seuils de `pg_trgm` et passent par l'index trigramme de `title_normalized`.
_BY_OWN_TITLE_SQL = text(
    _candidates_sql(_TITLE_SIMILARITY, "c.title_normalized % :title", ranked=True)
)

_BY_WORDS_SQL = text(
    _candidates_sql(
        "word_similarity(:title, c.title_normalized)", ":title <% c.title_normalized", ranked=True
    )
)

_BY_ID_SQL = text(_candidates_sql(_TITLE_SIMILARITY, "c.id = :id"))

_BY_DOI_SQL = text(_candidates_sql(_TITLE_SIMILARITY, "lower(c.doi) = :doi"))

_OWN_TITLE_SQL = text("SELECT title_normalized FROM publications WHERE id = :publication")


class MergeCandidateQueries:
    _conn: Connection

    def merge_candidates(self, publication_id: int, query: str = "") -> list[MergeCandidateOut]:
        """Renvoie les publications fusionnables avec `publication_id`. Sans `query` : titres proches du sien. Avec `query` : la publication de cet identifiant, de ce DOI, ou les titres proches de `query`."""
        query = query.strip()
        own_title = self._conn.execute(_OWN_TITLE_SQL, {"publication": publication_id}).scalar()
        params: dict[str, object] = {"publication": publication_id, "title": own_title or ""}
        if query.isdigit():
            rows = self._conn.execute(_BY_ID_SQL, {**params, "id": int(query)})
        elif doi := DOI.try_parse(query):
            rows = self._conn.execute(_BY_DOI_SQL, {**params, "doi": str(doi)})
        elif query:
            rows = self._conn.execute(_BY_WORDS_SQL, {**params, "title": normalize_text(query)})
        elif own_title:
            rows = self._conn.execute(_BY_OWN_TITLE_SQL, params)
        else:
            return []
        return [
            MergeCandidateOut(
                publication_id=r.id,
                title=r.title,
                publication_year=r.publication_year,
                doc_type=r.doc_type,
                doi=r.doi,
                similarity=r.similarity,
                sources=r.sources,
            )
            for r in rows
        ]
