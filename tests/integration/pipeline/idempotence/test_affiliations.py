"""Idempotence : phase `populate_affiliations` (propagation périmètre/structures)."""

from infrastructure.db.queues import Queue
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.config import set_config
from tests.integration.helpers.groups import group_ungrouped
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import insert_perimeter, insert_structure, insert_tutelle


def _setup_affiliations_test_data(conn):
    """Crée des données pour tester populate_affiliations :
    structures + périmètres + adresses + source_contributions liées.

    Scénario : une structure UCA (labo, id=80001) sous la tutelle
    d'UCA (id=80000). Une contribution OpenAlex est rattachée
    au labo via une adresse résolue. Une contribution HAL coexiste sans
    résolution d'adresse (sert pour l'idempotence des comptages).
    """

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

    # `source_contribution_structures` (matview) filtre par `perimeter_structures` :
    # peupler la clôture du périmètre depuis les perimeters/relations semés.
    from pipeline.transformation.structures.perimeter import refresh_perimeter_structures

    refresh_perimeter_structures(conn)


def _run_populate_affiliations(conn):
    """Exécute populate_affiliations sur la Connection SA de test."""
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
    """populate_affiliations produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        _setup_affiliations_test_data(sa_sync_conn)

        _run_populate_affiliations(sa_sync_conn)
        counts_1 = _count_affiliations(sa_sync_conn)

        # HAL utilise maintenant le circuit adresses (comme les autres sources).
        # Sans populate_addresses + resolve_addresses dans ce test, HAL n'est pas in_perimeter.
        # L'idempotence est vérifiée par la comparaison counts_1 == counts_2 ci-dessous.
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
        """Régression : populate doit traiter toutes les sources sans filtre.

        Une weekly avec --sources=hal ne doit plus laisser les SAs OpenAlex
        bloquées sans structure_ids quand leur adresse a été résolue entre
        deux runs (cas observé sur publication 21743 : adresse UCA résolue mais
        Marc Ruivard / Olivier Aumaître côté OA restés sans structure_ids
        car la weekly run ne ciblait que hal+scanr).
        """
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
    """Régression : les contributions theses doivent obtenir `in_perimeter` comme
    les autres sources (le sync est source-agnostique, dérivé de la matview).
    Avant fix, `BIBLIO_SOURCES` excluait theses → `in_perimeter` restait FALSE et
    la cascade personnes ne voyait jamais ces contributions (jury, directeurs,
    rapporteurs, voire auteurs)."""

    def test_theses_contribution_in_perimeter_via_address(self, sa_sync_conn):
        from sqlalchemy import text

        _setup_affiliations_test_data(sa_sync_conn)

        # Ajoute une source_record + source_contribution theses,
        # liées à l'adresse 80001 (déjà résolue vers structure 80001
        # via address_structures par _setup_affiliations_test_data).
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
    """Régression : un enregistrement sans publication qui entre dans le périmètre après sa normalisation n'était jamais mis en publication, faute d'être marqué pour la réconciliation (1 936 publications UCA créées tardivement en septembre 2026)."""

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

    def test_groupes_des_contributions_sources_entrees_marques(self, sa_sync_conn):
        """Le groupe d'une contribution source dont les indices de périmètre changent est marqué pour la recomposition de ses attributs."""
        from sqlalchemy import text

        _setup_affiliations_test_data(sa_sync_conn)
        group_ungrouped(sa_sync_conn)
        clear(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_GROUP_ATTRIBUTES)

        _run_populate_affiliations(sa_sync_conn)

        group = sa_sync_conn.execute(
            text(
                "SELECT contribution_id FROM aligned_source_contributions"
                " WHERE source_contribution_id = 80002"
            )
        ).scalar_one()
        assert group in queued(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_GROUP_ATTRIBUTES)

    def test_recalcul_cible_recompose_le_groupe(self, sa_sync_conn):
        """Le recalcul après une correction d'adresse recompose tout de suite les indices du groupe de la contribution source."""
        from sqlalchemy import text

        from pipeline.transformation.structures.perimeter_evidence import (
            SourceContributionPerimeterRecompute,
        )

        _setup_affiliations_test_data(sa_sync_conn)
        group_ungrouped(sa_sync_conn)

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
