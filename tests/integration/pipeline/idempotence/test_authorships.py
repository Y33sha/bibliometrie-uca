"""Idempotence : phase `build_authorships` (construction des authorships canoniques)."""

from tests.integration.pipeline.idempotence.test_persons import (
    run_create_persons,
    setup_persons_test_data,
)


def _run_build_authorships(conn):
    """Exécute build_authorships sur la Connection SA de test."""
    import logging

    from application.pipeline.authorships.build_authorships import build
    from infrastructure.queries.pipeline.authorships_build import PgAuthorshipsBuildQueries

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
        text("SELECT COUNT(DISTINCT authorship_id) AS cnt FROM authorship_structures")
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


class TestBuildAuthorshipsRebuildFull:
    """`rebuild_full=True` purge la table et reconstruit sans erreur FK.

    Régression : `TRUNCATE TABLE authorships` était refusé par Postgres à cause de la FK `source_authorships.authorship_id`, même après avoir mis cette FK à NULL et même si la table était vide. Le fix remplace `TRUNCATE` par `DELETE`.
    """

    def test_rebuild_full_succeeds_and_converges(self, sa_sync_conn):
        import logging

        from application.pipeline.authorships.build_authorships import build
        from infrastructure.queries.pipeline.authorships_build import PgAuthorshipsBuildQueries

        setup_persons_test_data(sa_sync_conn)
        run_create_persons(sa_sync_conn)
        _run_build_authorships(sa_sync_conn)
        counts_before = _count_authorships_tables(sa_sync_conn)
        assert counts_before["total"] >= 3

        build(
            sa_sync_conn,
            PgAuthorshipsBuildQueries(),
            logging.getLogger("test"),
            rebuild_full=True,
        )
        counts_after = _count_authorships_tables(sa_sync_conn)

        assert counts_after == counts_before, (
            f"rebuild_full doit converger vers le même état !\n"
            f"  avant : {counts_before}\n  après : {counts_after}"
        )


def _snapshot_authorships_content(conn) -> list[tuple]:
    """Contenu d'`authorships` hors identité (id) : ce qui doit être identique
    entre un build incrémental et un rebuild full."""
    from sqlalchemy import text

    return [
        tuple(r)
        for r in conn.execute(
            text("""
                SELECT publication_id, person_id, author_position, is_corresponding,
                       in_perimeter, roles
                FROM authorships
                ORDER BY publication_id, person_id
            """)
        ).all()
    ]


class TestIncrementalEqualsFull:
    """Après une mutation des sources, le build incrémental (add + prune +
    recompute convergent) produit le même contenu que le rebuild full — seuls
    les `id` diffèrent (le full les renumérote). Garde-fou : c'est ce qui permet
    de retirer la purge du pipeline routinier."""

    def test_incremental_matches_full_after_mutation(self, sa_sync_conn):
        from sqlalchemy import text

        setup_persons_test_data(sa_sync_conn)
        run_create_persons(sa_sync_conn)
        _run_build_authorships(sa_sync_conn)

        # Mutation des sources : inverse un is_corresponding (divergence d'attribut)
        # et supprime une source_authorship (modifie l'ensemble des paires).
        sa_sync_conn.execute(
            text(
                "UPDATE source_authorships SET is_corresponding = NOT is_corresponding "
                "WHERE id = (SELECT min(id) FROM source_authorships "
                "            WHERE authorship_id IS NOT NULL)"
            )
        )
        sa_sync_conn.execute(
            text(
                "DELETE FROM source_authorships "
                "WHERE id = (SELECT max(id) FROM source_authorships "
                "            WHERE authorship_id IS NOT NULL)"
            )
        )

        # Build incrémental après mutation → snapshot.
        _run_build_authorships(sa_sync_conn)
        incremental = _snapshot_authorships_content(sa_sync_conn)

        # Rebuild full (purge + reconstruction) sur le même état source → snapshot.
        import logging

        from application.pipeline.authorships.build_authorships import build
        from infrastructure.queries.pipeline.authorships_build import PgAuthorshipsBuildQueries

        build(
            sa_sync_conn,
            PgAuthorshipsBuildQueries(),
            logging.getLogger("test"),
            rebuild_full=True,
        )
        full = _snapshot_authorships_content(sa_sync_conn)

        assert incremental == full, (
            "Le build incrémental doit produire le même contenu que le full.\n"
            f"  incrémental : {incremental}\n  full : {full}"
        )
