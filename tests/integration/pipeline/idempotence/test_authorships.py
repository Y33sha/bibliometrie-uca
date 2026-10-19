"""Idempotence : phase `build_authorships` (construction des authorships canoniques)."""

from tests.integration.pipeline.idempotence.test_persons import (
    run_create_persons,
    setup_persons_test_data,
)


def _run_build_authorships(conn):
    """Exécute build_authorships sur la Connection SA de test."""
    import logging

    from pipeline.transformation.publications.authorships.authorships_queries import (
        AuthorshipsBuild,
    )
    from pipeline.transformation.publications.authorships.build_authorships import build

    build(conn, AuthorshipsBuild(), logging.getLogger("test"))


def _count_authorships_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    counts["total"] = conn.execute(text("SELECT COUNT(*) AS cnt FROM authorships")).scalar_one()
    counts["in_perimeter"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM authorships WHERE in_perimeter = TRUE")
    ).scalar_one()
    counts["hal_fk"] = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM source_authorships sa "
            "JOIN source_publications sp ON sp.id = sa.source_publication_id "
            "JOIN authorships a ON a.publication_id = sp.publication_id "
            "AND a.person_id = sa.person_id WHERE sa.source = 'hal'"
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


def _snapshot_authorships_content(conn) -> list[tuple]:
    """Contenu d'`authorships` hors identifiant : ce qui doit être identique entre un build incrémental et un build sur table vide."""
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


class TestIncrementalEqualsFromScratch:
    """Après une mutation des sources, le build incrémental (ajout, retrait et recalcul en une passe) produit le même contenu qu'un build sur table vide. Seuls les identifiants diffèrent."""

    def test_incremental_matches_from_scratch_after_mutation(self, sa_sync_conn):
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
                "            WHERE person_id IS NOT NULL)"
            )
        )
        sa_sync_conn.execute(
            text(
                "DELETE FROM source_authorships "
                "WHERE id = (SELECT max(id) FROM source_authorships "
                "            WHERE person_id IS NOT NULL)"
            )
        )

        # Build incrémental après mutation → snapshot.
        _run_build_authorships(sa_sync_conn)
        incremental = _snapshot_authorships_content(sa_sync_conn)

        # Build sur table vide, sur le même état des sources → snapshot.
        sa_sync_conn.execute(text("DELETE FROM authorships"))
        _run_build_authorships(sa_sync_conn)
        from_scratch = _snapshot_authorships_content(sa_sync_conn)

        assert incremental == from_scratch, (
            "Le build incrémental doit produire le même contenu qu'un build sur table vide.\n"
            f"  incrémental : {incremental}\n  table vide : {from_scratch}"
        )
