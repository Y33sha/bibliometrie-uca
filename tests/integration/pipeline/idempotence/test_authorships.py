"""Idempotence : phase `build_authorships` (construction des authorships canoniques)."""

from tests.integration.pipeline.idempotence.test_persons import (
    run_create_persons,
    setup_persons_test_data,
)


def _run_build_authorships(conn):
    """Exécute build_authorships sur la Connection SA de test."""
    import logging

    from application.pipeline.authorships.build_authorships import build
    from infrastructure.db.queries.authorships_build import PgAuthorshipsBuildQueries

    build(conn, PgAuthorshipsBuildQueries(), logging.getLogger("test"))


def _count_authorships_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    counts["total"] = conn.execute(text("SELECT COUNT(*) AS cnt FROM authorships")).scalar_one()
    counts["in_perimeter"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM authorships WHERE in_perimeter = TRUE")
    ).scalar_one()
    counts["hal_fk"] = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM source_authorships "
            "WHERE authorship_id IS NOT NULL AND source = 'hal'"
        )
    ).scalar_one()
    counts["with_structs"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM authorships WHERE structure_ids IS NOT NULL")
    ).scalar_one()
    return counts


class TestBuildAuthorshipsIdempotence:
    """build_authorships produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        setup_persons_test_data(sa_sync_conn)
        run_create_persons(sa_sync_conn)

        _run_build_authorships(sa_sync_conn)
        counts_1 = _count_authorships_tables(sa_sync_conn)

        assert counts_1["total"] >= 3, f"Au moins 3 authorships, got {counts_1['total']}"
        assert counts_1["hal_fk"] >= 3, "Les FK HAL doivent être peuplées"

        _run_build_authorships(sa_sync_conn)
        counts_2 = _count_authorships_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )
