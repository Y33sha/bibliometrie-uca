"""Idempotence : phase `build_contributions` (construction des contributions canoniques)."""

from tests.integration.pipeline.idempotence.test_persons import (
    run_create_persons,
    setup_persons_test_data,
)


def _run_build_contributions(conn):
    """Exécute build_contributions sur la Connection SA de test."""
    import logging

    from pipeline.transformation.publications.contributions.build_contributions import build

    build(conn, logging.getLogger("test"))


def _count_contributions_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    counts["total"] = conn.execute(text("SELECT COUNT(*) AS cnt FROM contributions")).scalar_one()
    counts["in_perimeter"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM contributions WHERE in_perimeter = TRUE")
    ).scalar_one()
    counts["hal_fk"] = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM source_contributions sc "
            "JOIN source_records sr ON sr.id = sc.source_record_id "
            "JOIN contributions a ON a.publication_id = sr.publication_id "
            "AND a.person_id = sc.person_id WHERE sc.source = 'hal'"
        )
    ).scalar_one()
    counts["with_structs"] = conn.execute(
        text("SELECT COUNT(DISTINCT contribution_id) AS cnt FROM contribution_structures")
    ).scalar_one()
    return counts


class TestBuildContributionsIdempotence:
    """build_contributions produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        setup_persons_test_data(sa_sync_conn)
        run_create_persons(sa_sync_conn)

        _run_build_contributions(sa_sync_conn)
        counts_1 = _count_contributions_tables(sa_sync_conn)

        assert counts_1["total"] >= 3, f"Au moins 3 contributions, got {counts_1['total']}"
        assert counts_1["hal_fk"] >= 3, "Les FK HAL doivent être peuplées"

        _run_build_contributions(sa_sync_conn)
        counts_2 = _count_contributions_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )
