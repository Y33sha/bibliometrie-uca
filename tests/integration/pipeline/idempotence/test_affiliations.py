"""Idempotence : phase `populate_affiliations` (propagation périmètre/structures)."""


def _setup_affiliations_test_data(conn):
    """Crée des données pour tester populate_affiliations :
    structures + périmètres + adresses + source_authorships liées.

    Scénario : une structure UCA (labo, id=80001) avec une relation
    est_tutelle_de → UCA (id=80000). Un authorship OpenAlex est rattaché
    au labo via une adresse résolue. Un authorship HAL coexiste sans
    résolution d'adresse (sert pour l'idempotence des comptages).
    """
    from sqlalchemy import text

    conn.execute(
        text("""
            INSERT INTO config (key, value) VALUES
                ('perimeter_affiliations', '"uca_wide"'),
                ('perimeter_persons', '"uca"')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """)
    )

    conn.execute(
        text("""
            INSERT INTO perimeters (code, name, structure_ids) VALUES
                ('uca', 'UCA restreint', ARRAY[80000]),
                ('uca_wide', 'UCA large', ARRAY[80000])
            ON CONFLICT (code) DO UPDATE SET structure_ids = EXCLUDED.structure_ids
        """)
    )

    conn.execute(
        text("""
            INSERT INTO structures (id, code, name, acronym, structure_type)
            VALUES (80000, 'UCA', 'Université Clermont Auvergne', 'UCA', 'universite'),
                   (80001, 'LABO-TEST', 'Laboratoire Test', 'LT', 'labo')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO structure_relations (parent_id, child_id, relation_type)
            VALUES (80000, 80001, 'est_tutelle_de')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
            VALUES (80001, 'Pub Affiliation Test', 'pub affiliation test', 'article', 2024)
        """)
    )

    conn.execute(
        text("""
            INSERT INTO source_publications (id, source, source_id, title, pub_year, doc_type, publication_id)
            VALUES (80001, 'hal', 'hal-80000001', 'Pub Affiliation Test', 2024, 'ART', 80001),
                   (80002, 'openalex', 'W80000001', 'Pub Affiliation Test', 2024, 'article', 80001)
        """)
    )

    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position,
                 in_perimeter, author_name_normalized)
            VALUES (80001, 'hal', 80001, 0, FALSE, 'alice dupont')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position,
                 in_perimeter, author_name_normalized)
            VALUES (80002, 'openalex', 80002, 0, FALSE, 'alice dupont')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO addresses (id, raw_text, normalized_text)
            VALUES (80001, 'Laboratoire Test, UCA, Clermont-Ferrand', 'laboratoire test uca clermont ferrand')
        """)
    )
    conn.execute(
        text("""
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (80001, 80001, TRUE)
        """)
    )
    conn.execute(
        text("""
            INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
            VALUES (80002, 80001)
        """)
    )


def _run_populate_affiliations(conn):
    """Exécute populate_affiliations sur la Connection SA de test."""
    import logging

    from application.pipeline.affiliations.populate_affiliations import (
        _step_address_source,
        step3d_theses,
    )
    from infrastructure.perimeter import get_affiliations_structure_ids, get_persons_structure_ids
    from infrastructure.queries.affiliations import PgAffiliationsQueries

    perimeter_ids = get_persons_structure_ids(conn)
    wide_ids = get_affiliations_structure_ids(conn)
    queries = PgAffiliationsQueries()
    logger = logging.getLogger("test")

    for source in ["hal", "openalex", "wos", "scanr"]:
        _step_address_source(conn, queries, logger, source, perimeter_ids, wide_ids)
    step3d_theses(conn, queries, logger, wide_ids)


def _count_affiliations(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for src in ["hal", "openalex"]:
        counts[f"{src}_in_perimeter"] = conn.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM source_authorships "
                "WHERE source = :src AND in_perimeter = TRUE"
            ),
            {"src": src},
        ).scalar_one()
        counts[f"{src}_with_structs"] = conn.execute(
            text(
                "SELECT COUNT(DISTINCT sa.id) AS cnt FROM source_authorships sa "
                "JOIN source_authorship_structures sas ON sas.source_authorship_id = sa.id "
                "WHERE sa.source = :src"
            ),
            {"src": src},
        ).scalar_one()
    return counts


class TestPopulateAffiliationsIdempotence:
    """populate_affiliations produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        _setup_affiliations_test_data(sa_sync_conn)

        _run_populate_affiliations(sa_sync_conn)
        counts_1 = _count_affiliations(sa_sync_conn)

        # HAL utilise maintenant le circuit adresses (comme les autres sources).
        # Sans populate_addresses + resolve_addresses dans ce test, HAL n'est pas in_perimeter.
        # L'idempotence est vérifiée par la comparaison counts_1 == counts_2 ci-dessous.
        assert counts_1["openalex_in_perimeter"] == 1, "L'authorship OA doit être in_perimeter"
        assert counts_1["openalex_with_structs"] == 1, (
            "L'authorship OA doit avoir des structure_ids"
        )

        _run_populate_affiliations(sa_sync_conn)
        counts_2 = _count_affiliations(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_run_populate_is_source_agnostic(self, sa_sync_conn):
        """Régression : run_populate doit traiter toutes les sources sans filtre.

        Une weekly avec --sources=hal ne doit plus laisser les SAs OpenAlex
        bloquées sans structure_ids quand leur adresse a été résolue entre
        deux runs (cas observé sur pub 21743 : adresse UCA résolue mais
        Marc Ruivard / Olivier Aumaître côté OA restés sans structure_ids
        car la weekly run ne ciblait que hal+scanr).
        """
        import logging

        from sqlalchemy import text

        from application.pipeline.affiliations.populate_affiliations import run_populate
        from infrastructure.perimeter import (
            get_affiliations_structure_ids,
            get_persons_structure_ids,
        )
        from infrastructure.queries.affiliations import PgAffiliationsQueries

        _setup_affiliations_test_data(sa_sync_conn)

        run_populate(
            sa_sync_conn,
            PgAffiliationsQueries(),
            logging.getLogger("test"),
            get_persons_structure_ids(sa_sync_conn),
            get_affiliations_structure_ids(sa_sync_conn),
        )

        row = sa_sync_conn.execute(
            text(
                "SELECT sa.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM source_authorship_structures "
                "        WHERE source_authorship_id = sa.id) AS structure_ids "
                "FROM source_authorships sa WHERE sa.id = 80002"
            )
        ).one()
        assert row.in_perimeter is True
        assert row.structure_ids == [80001]
