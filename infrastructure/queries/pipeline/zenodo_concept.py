"""Query service : SQL de la sous-étape de résolution du concept DOI Zenodo.

Appelé par `application/pipeline/publications/resolve_zenodo_concept.py`.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.zenodo_concept import ZenodoSourcePublication


def fetch_zenodo_source_publications_without_concept(
    conn: Connection,
) -> list[ZenodoSourcePublication]:
    # Le motif DOI Zenodo est dupliqué côté SQL (cf. `ZENODO_DOI_RE` côté
    # domain) : le filtrage en base évite de charger tout le stock.
    rows = conn.execute(
        text(r"""
            SELECT id, doi
            FROM source_publications
            WHERE doi ~* '10\.5281/zenodo\.\d+'
              AND external_ids -> 'zenodo_concept_doi' IS NULL
            ORDER BY id
        """)
    ).all()
    return [ZenodoSourcePublication(id=r.id, doi=r.doi) for r in rows]


def set_concept_doi(conn: Connection, source_publication_id: int, concept_doi: str) -> None:
    # `updated_at` est bumpé pour qu'une SP déjà rattachée à une publication
    # redevienne stale : `match_or_create` re-promeut alors le DOI canonique
    # vers le concept et fusionne les doublons concept/version (cas inter-run).
    conn.execute(
        text("""
            UPDATE source_publications
            SET external_ids = external_ids
                || jsonb_build_object('zenodo_concept_doi', CAST(:concept_doi AS text)),
                updated_at = now()
            WHERE id = :id
        """),
        {"concept_doi": concept_doi, "id": source_publication_id},
    )


class PgZenodoConceptQueries:
    """Implémentation Postgres de `ZenodoConceptQueries`."""

    def fetch_zenodo_source_publications_without_concept(
        self, conn: Connection
    ) -> list[ZenodoSourcePublication]:
        return fetch_zenodo_source_publications_without_concept(conn)

    def set_concept_doi(
        self, conn: Connection, source_publication_id: int, concept_doi: str
    ) -> None:
        set_concept_doi(conn, source_publication_id, concept_doi)
