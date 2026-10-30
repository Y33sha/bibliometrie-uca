"""Phase `affiliations` (`populate`) : indices de périmètre et structures des contributions sources, idempotence, marquages en aval."""

from infrastructure.db.queues import Queue
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.alignment import align_unaligned
from tests.integration.helpers.config import set_config
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import insert_perimeter, insert_structure, insert_tutelle


def _setup_affiliations_test_data(conn):
    """Insère un laboratoire (80001) sous la tutelle de l'université (80000), racine des périmètres. Une publication et ses enregistrements sources HAL et OpenAlex, chacun avec une contribution source. Seule la contribution source OpenAlex a une adresse, rattachée au laboratoire."""

    set_config(conn, "perimeter_extraction", "alliance_uca")
    set_config(conn, "perimeter_persons", "uca")
    insert_perimeter(conn, "uca", root_structure_ids=[80000], name="UCA restreint", replace=True)
    insert_perimeter(
        conn, "alliance_uca", root_structure_ids=[80000], name="UCA large", replace=True
    )
    insert_structure(
        conn,
        "UCA",
        row_id=80000,
        name="Université Clermont Auvergne",
        acronym="UCA",
        structure_type="universite",
    )
    insert_structure(conn, "LABO-TEST", row_id=80001, name="Laboratoire Test", acronym="LT")
    insert_tutelle(conn, 80000, child_id=80001)

    insert_publication(conn, "Pub Affiliation Test", row_id=80001)

    for row_id, source, source_id, doc_type in (
        (80001, "hal", "hal-80000001", "article"),
        (80002, "openalex", "W80000001", "article"),
    ):
        insert_source_record(
            conn,
            80001,
            source=source,
            source_id=source_id,
            title="Pub Affiliation Test",
            row_id=row_id,
            publication_year=2024,
            doc_type=doc_type,
        )
        insert_source_contribution(
            conn,
            row_id,
            source=source,
            row_id=row_id,
            raw_author_name="Alice Dupont",
            author_name_normalized="alice dupont",
            in_perimeter=False,
        )

    insert_address(
        conn,
        "Laboratoire Test, UCA, Clermont-Ferrand",
        row_id=80001,
        normalized_text="laboratoire test uca clermont ferrand",
    )
    insert_address_structure(conn, 80001, structure_id=80001, is_confirmed=True)
    insert_source_contribution_address(conn, 80002, address_id=80001)

    # La vue `source_contribution_structures` filtre sur `perimeter_structures` : calcule la clôture des périmètres semés.
    from pipeline.transformation.structures.perimeter import refresh_perimeter_structures

    refresh_perimeter_structures(conn)


def _run_populate_affiliations(conn):
    """Exécute `populate` sur la connexion du test."""
    import logging

    from infrastructure.read_models.perimeters.queries import get_persons_structure_ids
    from pipeline.transformation.structures.affiliations import populate

    populate(
        conn,
        logging.getLogger("test"),
        get_persons_structure_ids(conn),
    )


def _count_affiliations(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for src in ["hal", "openalex"]:
        counts[f"{src}_in_perimeter"] = conn.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM source_contributions "
                "WHERE source = :src AND in_perimeter = TRUE"
            ),
            {"src": src},
        ).scalar_one()
        counts[f"{src}_with_structs"] = conn.execute(
            text(
                "SELECT COUNT(DISTINCT sc.id) AS cnt FROM source_contributions sc "
                "JOIN source_contribution_structures scs ON scs.source_contribution_id = sc.id "
                "WHERE sc.source = :src"
            ),
            {"src": src},
        ).scalar_one()
    return counts


class TestPopulateAffiliationsIdempotence:
    """`populate` lancé deux fois donne le même résultat."""

    def test_double_run_same_counts(self, sa_sync_conn):
        _setup_affiliations_test_data(sa_sync_conn)

        _run_populate_affiliations(sa_sync_conn)
        counts_1 = _count_affiliations(sa_sync_conn)

        # La contribution source HAL, sans adresse, reste hors périmètre.
        assert counts_1["openalex_in_perimeter"] == 1, "La contribution OA doit être in_perimeter"
        assert counts_1["openalex_with_structs"] == 1, (
            "La contribution OA doit avoir des structure_ids"
        )

        _run_populate_affiliations(sa_sync_conn)
        counts_2 = _count_affiliations(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_populate_is_source_agnostic(self, sa_sync_conn):
        """`populate` traite toutes les sources : une contribution source OpenAlex reçoit sa structure, même hors d'un run limité à OpenAlex."""
        import logging

        from sqlalchemy import text

        from infrastructure.read_models.perimeters.queries import get_persons_structure_ids
        from pipeline.transformation.structures.affiliations import populate

        _setup_affiliations_test_data(sa_sync_conn)

        populate(
            sa_sync_conn,
            logging.getLogger("test"),
            get_persons_structure_ids(sa_sync_conn),
        )

        row = sa_sync_conn.execute(
            text(
                "SELECT sc.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM source_contribution_structures "
                "        WHERE source_contribution_id = sc.id) AS structure_ids "
                "FROM source_contributions sc WHERE sc.id = 80002"
            )
        ).one()
        assert row.in_perimeter is True
        assert row.structure_ids == [80001]


class TestPopulateAffiliationsTheses:
    """Les contributions sources de theses.fr (jury, directeurs, rapporteurs, auteurs) reçoivent leurs indices de périmètre comme celles des autres sources, donc entrent dans la phase `persons`."""

    def test_theses_contribution_in_perimeter_via_address(self, sa_sync_conn):
        from sqlalchemy import text

        _setup_affiliations_test_data(sa_sync_conn)

        # Enregistrement source theses.fr et sa contribution source, liée à l'adresse 80001, rattachée au laboratoire.
        insert_source_record(
            sa_sync_conn,
            80001,
            source="theses",
            source_id="2024UCFA0001",
            title="Thèse Test",
            row_id=80003,
            publication_year=2024,
            doc_type="thesis",
        )
        insert_source_contribution(
            sa_sync_conn,
            80003,
            source="theses",
            row_id=80003,
            raw_author_name="Alice Dupont",
            author_name_normalized="alice dupont",
            in_perimeter=False,
            roles=["author"],
        )
        insert_source_contribution_address(sa_sync_conn, 80003, address_id=80001)

        _run_populate_affiliations(sa_sync_conn)

        row = sa_sync_conn.execute(
            text(
                "SELECT sc.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM source_contribution_structures "
                "        WHERE source_contribution_id = sc.id) AS structure_ids "
                "FROM source_contributions sc WHERE sc.id = 80003"
            )
        ).one()
        assert row.in_perimeter is True
        assert row.structure_ids == [80001]


def _marked_for_reconciliation(conn, source_record_id: int) -> bool:
    return source_record_id in queued(conn, Queue.SOURCE_RECORD_KEYS)


class TestEntreeDansLePerimetre:
    """Un enregistrement source sans publication, entré dans le périmètre après sa normalisation, est marqué pour la réconciliation."""

    def _orpheline(self, conn) -> None:
        from sqlalchemy import text

        conn.execute(text("UPDATE source_records SET publication_id = NULL WHERE id = 80002"))
        clear(conn, Queue.SOURCE_RECORD_KEYS)

    def test_enregistrement_sans_publication_marque(self, sa_sync_conn):
        _setup_affiliations_test_data(sa_sync_conn)
        self._orpheline(sa_sync_conn)

        _run_populate_affiliations(sa_sync_conn)

        assert _marked_for_reconciliation(sa_sync_conn, 80002) is True

    def test_enregistrement_en_publication_non_marque(self, sa_sync_conn):
        _setup_affiliations_test_data(sa_sync_conn)
        clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

        _run_populate_affiliations(sa_sync_conn)

        assert _marked_for_reconciliation(sa_sync_conn, 80002) is False

    def test_contributions_des_contributions_sources_entrees_marquees(self, sa_sync_conn):
        """La contribution d'une contribution source dont les indices de périmètre changent est marquée pour la recomposition de ses attributs."""
        from sqlalchemy import text

        _setup_affiliations_test_data(sa_sync_conn)
        align_unaligned(sa_sync_conn)
        clear(sa_sync_conn, Queue.CONTRIBUTION_ATTRIBUTES)

        _run_populate_affiliations(sa_sync_conn)

        contribution = sa_sync_conn.execute(
            text(
                "SELECT contribution_id FROM aligned_source_contributions"
                " WHERE source_contribution_id = 80002"
            )
        ).scalar_one()
        assert contribution in queued(sa_sync_conn, Queue.CONTRIBUTION_ATTRIBUTES)

    def test_recalcul_cible_recompose_la_contribution(self, sa_sync_conn):
        """Le recalcul après une correction d'adresse recompose aussitôt les indices de périmètre de la contribution qui contient la contribution source."""
        from sqlalchemy import text

        from pipeline.transformation.structures.perimeter_evidence import (
            SourceContributionPerimeterRecompute,
        )

        _setup_affiliations_test_data(sa_sync_conn)
        align_unaligned(sa_sync_conn)

        SourceContributionPerimeterRecompute(sa_sync_conn).recompute_perimeter(
            [80002], [80000, 80001]
        )

        assert sa_sync_conn.execute(
            text(
                "SELECT g.in_perimeter FROM contributions g"
                " JOIN aligned_source_contributions m ON m.contribution_id = g.id"
                " WHERE m.source_contribution_id = 80002"
            )
        ).scalar_one()

    def test_recalcul_cible_marque_l_enregistrement_sans_publication(self, sa_sync_conn):
        from pipeline.transformation.structures.perimeter_evidence import (
            SourceContributionPerimeterRecompute,
        )

        _setup_affiliations_test_data(sa_sync_conn)
        self._orpheline(sa_sync_conn)

        SourceContributionPerimeterRecompute(sa_sync_conn).recompute_perimeter(
            [80002], [80000, 80001]
        )

        assert _marked_for_reconciliation(sa_sync_conn, 80002) is True
