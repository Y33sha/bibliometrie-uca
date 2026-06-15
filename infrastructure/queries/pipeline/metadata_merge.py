"""Query service : candidats à la fusion par métadonnées (thèse / proceedings).

Implémente `MetadataMergeQueries`. La détection de paires est ici ; les critères
(auteur primary thèse, nombre d'auteurs) réutilisent les fonctions de lecture
déjà écrites pour le matching (`publications_match_or_create`).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.metadata_merge import (
    MetadataMergeCandidatePair,
    MetadataMergeQueries,
)
from infrastructure.queries.pipeline.publications_match_or_create import (
    fetch_max_source_authorship_count_per_publication,
    fetch_thesis_primary_author,
)


def find_metadata_merge_candidate_pairs(conn: Connection) -> list[MetadataMergeCandidatePair]:
    """Paires de publications (id_a < id_b) au même `title_normalized` + `pub_year`,
    dans la même famille de doc_type (thèse/thèse-en-cours, ou proceedings),
    hors paires déjà marquées distinctes.

    Critères doc_type-spécifiques (auteur, compteur, longueur de titre) appliqués
    par l'appelant. Bénéficie de `idx_publications_titlenorm_year`.
    """
    rows = conn.execute(
        text("""
            SELECT p1.id AS id_a, p2.id AS id_b,
                   p1.doc_type::text AS doc_type_a, p2.doc_type::text AS doc_type_b,
                   p1.title_normalized AS title_normalized
            FROM publications p1
            JOIN publications p2
                ON p1.id < p2.id
               AND p1.title_normalized = p2.title_normalized
               AND p1.pub_year = p2.pub_year
            WHERE p1.title_normalized IS NOT NULL AND p1.title_normalized <> ''
              AND (
                  (p1.doc_type IN ('thesis', 'ongoing_thesis')
                   AND p2.doc_type IN ('thesis', 'ongoing_thesis'))
                  OR (p1.doc_type = 'proceedings' AND p2.doc_type = 'proceedings')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM distinct_publications dp
                  WHERE dp.pub_id_a = p1.id AND dp.pub_id_b = p2.id
              )
            ORDER BY p1.id, p2.id
        """)
    ).all()
    return [
        MetadataMergeCandidatePair(
            id_a=r.id_a,
            id_b=r.id_b,
            doc_type_a=r.doc_type_a,
            doc_type_b=r.doc_type_b,
            title_normalized=r.title_normalized,
        )
        for r in rows
    ]


class PgMetadataMergeQueries(MetadataMergeQueries):
    """Adapter PostgreSQL pour `MetadataMergeQueries`."""

    def find_metadata_merge_candidate_pairs(
        self, conn: Connection
    ) -> list[MetadataMergeCandidatePair]:
        return find_metadata_merge_candidate_pairs(conn)

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None:
        return fetch_thesis_primary_author(conn, publication_id)

    def fetch_max_source_authorship_count_per_publication(
        self, conn: Connection, publication_id: int
    ) -> int:
        return fetch_max_source_authorship_count_per_publication(conn, publication_id)
