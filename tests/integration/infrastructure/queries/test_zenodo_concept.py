"""Tests d'intégration pour `infrastructure.queries.pipeline.zenodo_concept`.

Vérifie que `fetch_zenodo_source_publications_without_concept` ne remonte que
les SP au DOI Zenodo sans `zenodo_concept_doi`, et que `set_concept_doi` pose le
concept (les faisant donc sortir du pool au fetch suivant).
"""

from sqlalchemy import text

from infrastructure.queries.pipeline.zenodo_concept import PgZenodoConceptQueries


def _insert_sp(conn, *, source_id, doi, external_ids="{}"):
    row = conn.execute(
        text("""
            INSERT INTO source_publications (source, source_id, title, doi, external_ids)
            VALUES (CAST('openalex' AS source_type), :sid, 'T', :doi, CAST(:ext AS jsonb))
            RETURNING id
        """),
        {"sid": source_id, "doi": doi, "ext": external_ids},
    ).one()
    return row.id


class TestZenodoConceptQueries:
    def test_fetch_then_set_concept(self, sa_sync_conn):
        queries = PgZenodoConceptQueries()

        zenodo_id = _insert_sp(sa_sync_conn, source_id="z-1", doi="10.5281/zenodo.12345")
        # SP au DOI Zenodo mais concept déjà posé -> exclue du pool.
        _insert_sp(
            sa_sync_conn,
            source_id="z-2",
            doi="10.5281/zenodo.67890",
            external_ids='{"zenodo_concept_doi": "10.5281/zenodo.67000"}',
        )
        # SP non-Zenodo -> exclue du pool.
        _insert_sp(sa_sync_conn, source_id="other", doi="10.1038/nature123")

        pending = queries.fetch_zenodo_source_publications_without_concept(sa_sync_conn)
        ids = {sp.id for sp in pending}
        assert zenodo_id in ids
        target = next(sp for sp in pending if sp.id == zenodo_id)
        assert target.doi == "10.5281/zenodo.12345"

        queries.set_concept_doi(sa_sync_conn, zenodo_id, "10.5281/zenodo.12000")

        # Le concept étant posé, la SP sort du pool.
        remaining = queries.fetch_zenodo_source_publications_without_concept(sa_sync_conn)
        assert zenodo_id not in {sp.id for sp in remaining}

        stored = sa_sync_conn.execute(
            text(
                "SELECT external_ids -> 'zenodo_concept_doi' AS c "
                "FROM source_publications WHERE id = :id"
            ),
            {"id": zenodo_id},
        ).scalar_one()
        assert stored == "10.5281/zenodo.12000"
