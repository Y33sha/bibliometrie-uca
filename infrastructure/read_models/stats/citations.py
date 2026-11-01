"""Indicateurs de citation de chaque publication, pour le nuage de points d'un dashboard."""

from sqlalchemy import Connection, text

from domain.normalize import to_plain_text
from infrastructure.read_models.publications.filtering import (
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.models import CitationPoint, CitationPointsResponse
from infrastructure.sql_fragments import cited_by_count, fwci


class StatsCitationQueries:
    _conn: Connection

    def citation_points(self, *, filters: PublicationFilters) -> CitationPointsResponse:
        """Renvoie les publications pourvues d'un nombre de citations sous les filtres, avec leur année et leur FWCI."""
        where, binds = publication_filter_where(filters, filter_context(self._conn, filters))
        self._conn.execute(text("SET LOCAL jit = off"))
        rows = self._conn.execute(
            text(f"""
                SELECT p.id, p.title, p.publication_year AS year,
                       {cited_by_count()} AS cited_by_count, {fwci()} AS fwci
                FROM publications p
                WHERE {where} AND {cited_by_count()} IS NOT NULL
                ORDER BY p.id
            """),
            binds,
        )
        # Titre en texte brut : l'infobulle d'un canevas affiche le balisage tel quel.
        return CitationPointsResponse(
            points=[
                CitationPoint(
                    id=r.id,
                    title=to_plain_text(r.title),
                    year=r.year,
                    cited_by_count=r.cited_by_count,
                    fwci=r.fwci,
                )
                for r in rows
            ]
        )
