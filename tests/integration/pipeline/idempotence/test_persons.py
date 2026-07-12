"""Idempotence : phase personnes (reset / match / create)."""


def setup_persons_test_data(conn):
    """Crée une chaîne complète de données pour tester create_persons :
    publications → source_publications (hal) → source_authorships (in_perimeter=TRUE).
    """
    from sqlalchemy import text

    from tests.integration.helpers.authorships import upsert_identity

    # Publications
    conn.execute(
        text("""
            INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
            VALUES (90001, 'Test Pub Alpha', 'test pub alpha', 'article', 2024),
                   (90002, 'Test Pub Beta', 'test pub beta', 'thesis', 2024)
        """)
    )

    # HAL documents
    conn.execute(
        text("""
            INSERT INTO source_publications (id, source, source_id, title, pub_year, doc_type, publication_id)
            VALUES (90001, 'hal', 'hal-90000001', 'Test Pub Alpha', 2024, 'ART', 90001),
                   (90002, 'hal', 'hal-90000002', 'Test Pub Beta', 2024, 'THESE', 90002)
        """)
    )

    # HAL authorships — les identifiants observés (orcid + hal_person_id) vivent
    # sur l'identité. Eve Leroy (hal_person_id=900001, orcid renseigné) apparaît
    # sur les 2 pubs et partage donc une seule identité. Frank Moreau
    # (hal_person_id=900002) sur la pub 90001. Grace Petit (sans identifiant) sur
    # la pub 90002.
    eve = upsert_identity(
        conn, "eve leroy", {"orcid": "0000-0001-9999-0001", "hal_person_id": 900001}
    )
    frank = upsert_identity(conn, "frank moreau", {"hal_person_id": 900002})
    grace = upsert_identity(conn, "grace petit", None)
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position, in_perimeter,
                 person_id, raw_author_name, identity_id)
            VALUES
                (90001, 'hal', 90001, 0, TRUE, NULL, 'Eve Leroy', :eve),
                (90002, 'hal', 90001, 1, TRUE, NULL, 'Frank Moreau', :frank),
                (90003, 'hal', 90002, 0, TRUE, NULL, 'Eve Leroy', :eve),
                (90004, 'hal', 90002, 1, TRUE, NULL, 'Grace Petit', :grace)
        """),
        {"eve": eve, "frank": frank, "grace": grace},
    )


def run_create_persons(conn):
    """Exécute create_persons sur la Connection SA de test, retourne le
    nombre d'authorships HAL rattachées à l'issue du run."""
    import logging

    from sqlalchemy import text

    from application.pipeline.persons.cascade import run_cascade
    from application.pipeline.persons.reset import reset
    from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
    from infrastructure.repositories import person_repository

    queries = PgPersonsCreateQueries()
    logger = logging.getLogger("test")
    repo = person_repository(conn)
    reset(conn, queries, logger, person_repo=repo)
    run_cascade(conn, queries, logger, person_repo=repo)

    return conn.execute(
        text(
            "SELECT COUNT(*) FROM source_authorships WHERE source = 'hal' AND person_id IS NOT NULL"
        )
    ).scalar_one()


def _count_persons_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for t in ("persons", "person_name_forms", "person_identifiers"):
        counts[t] = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {t}")).scalar_one()
    counts["hal_as_linked"] = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM source_authorships "
            "WHERE source = 'hal' AND person_id IS NOT NULL"
        )
    ).scalar_one()
    return counts


class TestCreatePersonsIdempotence:
    """create_persons produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        from sqlalchemy import text

        setup_persons_test_data(sa_sync_conn)

        # Passe 1
        linked_1 = run_create_persons(sa_sync_conn)
        counts_1 = _count_persons_tables(sa_sync_conn)

        assert linked_1 == 4, f"4 authorships à rattacher, got {linked_1}"
        assert counts_1["hal_as_linked"] == 4

        # Reset : remettre person_id à NULL sur les authorships
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET person_id = NULL WHERE source = 'hal'")
        )

        # Passe 2
        run_create_persons(sa_sync_conn)
        counts_2 = _count_persons_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_same_hal_person_id_one_person(self, sa_sync_conn):
        """Deux authorships avec le même hal_person_id → une seule personne."""
        from sqlalchemy import text

        setup_persons_test_data(sa_sync_conn)
        run_create_persons(sa_sync_conn)

        # Eve Leroy (hal_person_id=900001) apparaît sur 2 documents
        rows = sa_sync_conn.execute(
            text("""
                SELECT DISTINCT sa.person_id FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sa.source = 'hal'
                  AND aik.person_identifiers->>'hal_person_id' = '900001'
                  AND sa.person_id IS NOT NULL
            """)
        ).all()
        assert len(rows) == 1, "Eve Leroy devrait être une seule personne"

    def test_orcid_registered(self, sa_sync_conn):
        """L'ORCID d'Eve Leroy est enregistré dans person_identifiers."""
        from sqlalchemy import text

        setup_persons_test_data(sa_sync_conn)
        run_create_persons(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("""
                SELECT COUNT(*) AS cnt FROM person_identifiers
                WHERE id_type = 'orcid' AND id_value = '0000-0001-9999-0001'
            """)
        ).scalar_one()
        assert cnt == 1
