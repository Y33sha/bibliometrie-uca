"""Idempotence : phase personnes (arbitrage des conflits d'identifiant, cascade)."""


def setup_persons_test_data(conn):
    """Crée une chaîne complète de données pour tester create_persons :
    publications → source_publications (hal) → source_authorships (in_perimeter=TRUE).
    """

    from tests.integration.helpers.publications import insert_publication
    from tests.integration.helpers.sources import insert_signature, insert_source_publication

    # Publications
    insert_publication(conn, "Test Pub Alpha", row_id=90001)
    insert_publication(conn, "Test Pub Beta", row_id=90002, doc_type="thesis")

    # HAL documents
    for row_id, source_id, title, doc_type in (
        (90001, "hal-90000001", "Test Pub Alpha", "ART"),
        (90002, "hal-90000002", "Test Pub Beta", "THESE"),
    ):
        insert_source_publication(
            conn,
            row_id,
            source_id=source_id,
            title=title,
            row_id=row_id,
            pub_year=2024,
            doc_type=doc_type,
        )

    # HAL authorships — les identifiants observés (orcid + hal_person_id) vivent
    # sur l'identité. Eve Leroy (hal_person_id=900001, orcid renseigné) apparaît
    # sur les 2 pubs et partage donc une seule identité. Frank Moreau
    # (hal_person_id=900002) sur la pub 90001. Grace Petit (sans identifiant) sur
    # la pub 90002.
    eve = ("Eve Leroy", "eve leroy", {"orcid": "0000-0001-9999-0001", "hal_person_id": 900001})
    frank = ("Frank Moreau", "frank moreau", {"hal_person_id": 900002})
    grace = ("Grace Petit", "grace petit", None)
    for row_id, source_publication_id, position, (raw, normalized, identifiers) in (
        (90001, 90001, 0, eve),
        (90002, 90001, 1, frank),
        (90003, 90002, 0, eve),
        (90004, 90002, 1, grace),
    ):
        insert_signature(
            conn,
            source_publication_id,
            row_id=row_id,
            author_position=position,
            raw_author_name=raw,
            author_name_normalized=normalized,
            person_identifiers=identifiers,
            in_perimeter=True,
        )


def run_create_persons(conn):
    """Exécute create_persons sur la Connection SA de test, retourne le
    nombre d'authorships HAL rattachées à l'issue du run."""
    import logging

    from sqlalchemy import text

    from pipeline.transformation.persons.arbitrate_identifiers import arbitrate_identifier_conflicts
    from pipeline.transformation.persons.cascade import run_cascade
    from pipeline.transformation.persons.matching import PersonsMatchingQueries
    from pipeline.transformation.persons.person_writes import PersonWrites

    queries = PersonsMatchingQueries()
    logger = logging.getLogger("test")
    arbitrate_identifier_conflicts(conn, queries, logger, writes=PersonWrites(conn))
    run_cascade(conn, queries, logger, writes=PersonWrites(conn))

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
