"""Tests d'intégration pour `infrastructure.read_models.hal_problems.queries`."""

from functools import partial

from sqlalchemy import text

from infrastructure.read_models.hal_problems.models import NoMissingCollections
from infrastructure.read_models.hal_problems.queries import HalProblemsQueries
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.alignment import (
    add_aligned_source_contribution,
    align_source_contributions,
)
from tests.integration.helpers.config import set_config
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import (
    add_source_contribution_structure,
    add_to_perimeter,
    insert_structure,
)

# Enregistrement source de 2024, de titre « T ».
_source_record = partial(insert_source_record, title="T", publication_year=2024)


def _q(conn) -> HalProblemsQueries:
    return HalProblemsQueries(conn)


def _create_lab(conn, code="LAB", hal_collection=None, acronym=None):
    lab_id = insert_structure(conn, code, name="L", acronym=acronym, hal_collection=hal_collection)
    # Rattache au périmètre des personnes : les lectures HAL se limitent au périmètre, pas au type de structure.
    set_config(conn, "perimeter_persons", "uca")
    add_to_perimeter(conn, lab_id, code="uca", name="test persons perimeter")
    return lab_id


def _create_hal_source_contribution_with_hal_id(
    conn,
    *,
    person_id,
    hal_person_id,
    source_id="h-acc",
    raw_author_name="X",
    neutralized_identifiers=None,
):
    """Crée une contribution source HAL avec `hal_person_id` dans ses informations du contributeur, contribution source d'une contribution rattachée à `person_id`."""
    publication = insert_publication(
        conn, title=f"P-{source_id}", title_normalized=f"p-{source_id}"
    )
    source_record = _source_record(conn, publication, source_id=source_id)
    source_contribution = insert_source_contribution(
        conn,
        source_record,
        raw_author_name=raw_author_name,
        identifiers={"hal_person_id": hal_person_id},
        neutralized_identifiers=neutralized_identifiers,
    )
    contribution = align_source_contributions(
        conn, publication, [(source_contribution, source_record)]
    )
    conn.execute(
        text(
            "UPDATE contributions SET person_id = :person, resolution_mode = 'manual' WHERE id = :g"
        ),
        {"person": person_id, "g": contribution},
    )


def _attribute_hal_account(conn, person_id, hal_person_id, status=None):
    insert_person_identifier(
        conn, person_id, id_type="hal_person_id", id_value=str(hal_person_id), status=status
    )


class TestHalDuplicateAccounts:
    def test_details_each_attributed_account_by_its_contributions(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn)
        for hal_person_id, source_id, name in ((42, "hal-1", "A"), (43, "hal-2", "B")):
            _attribute_hal_account(sa_sync_conn, pid, hal_person_id)
            _create_hal_source_contribution_with_hal_id(
                sa_sync_conn,
                person_id=pid,
                hal_person_id=hal_person_id,
                source_id=source_id,
                raw_author_name=name,
            )

        res = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50)

        assert res.total == 1
        [ours] = res.persons
        assert ours.person_id == pid
        assert [(a.hal_person_id, a.full_name, a.publication_count) for a in ours.hal_accounts] == [
            (42, "A", 1),
            (43, "B", 1),
        ]

    def test_lists_an_attributed_account_absent_from_contributions(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn)
        _attribute_hal_account(sa_sync_conn, pid, 42)
        _attribute_hal_account(sa_sync_conn, pid, 43)

        [ours] = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50).persons

        assert [(a.full_name, a.publication_count) for a in ours.hal_accounts] == [
            (None, 0),
            (None, 0),
        ]

    def test_counts_only_the_contributions_of_the_person(self, sa_sync_conn):
        """Un compte attribué à la personne et présent dans les contributions d'une autre personne compte seulement les contributions de la personne."""
        pid = insert_person(sa_sync_conn)
        other = insert_person(sa_sync_conn)
        _attribute_hal_account(sa_sync_conn, pid, 42)
        _attribute_hal_account(sa_sync_conn, pid, 43)
        _create_hal_source_contribution_with_hal_id(
            sa_sync_conn, person_id=pid, hal_person_id=42, source_id="hal-1"
        )
        _create_hal_source_contribution_with_hal_id(
            sa_sync_conn, person_id=other, hal_person_id=42, source_id="hal-2"
        )

        [ours] = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50).persons

        assert [(a.hal_person_id, a.publication_count) for a in ours.hal_accounts] == [
            (42, 1),
            (43, 0),
        ]

    def test_ignores_contributions_neutralizing_the_account(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn)
        _attribute_hal_account(sa_sync_conn, pid, 42)
        _attribute_hal_account(sa_sync_conn, pid, 43)
        _create_hal_source_contribution_with_hal_id(
            sa_sync_conn,
            person_id=pid,
            hal_person_id=42,
            source_id="hal-1",
            neutralized_identifiers={"hal_person_id": "misplaced"},
        )

        [ours] = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50).persons

        assert [(a.hal_person_id, a.publication_count) for a in ours.hal_accounts] == [
            (42, 0),
            (43, 0),
        ]

    def test_ignores_single_account(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn)
        _attribute_hal_account(sa_sync_conn, pid, 42)
        res = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50)
        assert res.total == 0

    def test_ignores_rejected_attribution(self, sa_sync_conn):
        """Un compte rejeté pour la personne est ignoré, même présent dans ses contributions (publication mal attribuée)."""
        pid = insert_person(sa_sync_conn)
        _attribute_hal_account(sa_sync_conn, pid, 42)
        _attribute_hal_account(sa_sync_conn, pid, 43, status="rejected")
        _create_hal_source_contribution_with_hal_id(
            sa_sync_conn, person_id=pid, hal_person_id=43, source_id="hal-1"
        )
        res = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50)
        assert res.total == 0


class TestHalDuplicatePublicationsByDoi:
    def test_detects_two_hal_deposits_same_doi(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _source_record(sa_sync_conn, publication, source_id="h-1", doi="10.1/shared")
        _source_record(sa_sync_conn, publication, source_id="h-2", doi="10.1/shared")

        res = _q(sa_sync_conn).hal_duplicate_publications_by_doi(page=1, per_page=50)
        assert res.total >= 1
        assert any(len(p.halids) >= 2 for p in res.pairs)

    def test_details_each_pair_of_a_multi_pair_page(self, sa_sync_conn):
        """Le détail des publications se lit par lot : chaque paire de la page reçoit le sien."""
        expected = {}
        for i in (1, 2, 3):
            publication = insert_publication(
                sa_sync_conn, title=f"Doublon {i}", doi=f"10.1/dup-{i}"
            )
            _source_record(sa_sync_conn, publication, source_id=f"h-dup-{i}-a", doi=f"10.1/dup-{i}")
            _source_record(sa_sync_conn, publication, source_id=f"h-dup-{i}-b", doi=f"10.1/dup-{i}")
            expected[publication] = (f"Doublon {i}", {f"h-dup-{i}-a", f"h-dup-{i}-b"})

        res = _q(sa_sync_conn).hal_duplicate_publications_by_doi(page=1, per_page=50)

        assert res.total == 3
        served = {
            p.publication.id: (p.publication.title, {d.halid for d in p.publication.hal_docs})
            for p in res.pairs
        }
        assert served == expected

    def test_noop_without_duplicates(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _source_record(sa_sync_conn, publication, source_id="h-uniq", doi="10.1/u")
        res = _q(sa_sync_conn).hal_duplicate_publications_by_doi(page=1, per_page=50)
        assert res.total == 0

    def test_ignores_deposits_without_publication(self, sa_sync_conn):
        """Des dépôts sans publication qui partagent un DOI ne forment pas de paire."""
        _source_record(sa_sync_conn, None, source_id="h-out-1", doi="10.1/out")
        _source_record(sa_sync_conn, None, source_id="h-out-2", doi="10.1/out")
        res = _q(sa_sync_conn).hal_duplicate_publications_by_doi(page=1, per_page=50)
        assert res.total == 0
        assert res.pairs == []


class TestHalDuplicatePublicationsByMetadata:
    def test_detects_pair_with_same_title_and_year(self, sa_sync_conn):
        # Même titre normalisé de plus de 30 caractères, même année, même type, nombres d'auteurs HAL à ±2.
        title = "Article Title That Is Long Enough To Trigger Metadata Detection"
        title_norm = title.lower()
        p1 = insert_publication(sa_sync_conn, title=title, title_normalized=title_norm)
        p2 = insert_publication(sa_sync_conn, title=title, title_normalized=title_norm)
        _source_record(sa_sync_conn, p1, source_id="h-meta-1")
        _source_record(sa_sync_conn, p2, source_id="h-meta-2")

        res = _q(sa_sync_conn).hal_duplicate_publications_by_metadata(page=1, per_page=50)
        assert res.total >= 1


class TestHalMissingCollectionsLabs:
    def test_lists_labs_with_hal_collection(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn, code="LAB-1", hal_collection="COLL-X")
        _create_lab(sa_sync_conn, code="LAB-NO", hal_collection=None)

        labs = _q(sa_sync_conn).hal_missing_collections_labs()
        ids = [lab_.id for lab_ in labs]
        assert lab in ids
        assert all(lab_.hal_collection for lab_ in labs)


class TestHalMissingCollections:
    def test_reports_a_lab_without_collection(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn, code="LAB-NO-COL", hal_collection=None)
        res = _q(sa_sync_conn).hal_missing_collections(lab_id=lab, page=1, per_page=50)
        assert res is NoMissingCollections.NO_COLLECTION

    def test_reports_an_unknown_lab_apart(self, sa_sync_conn):
        """Un laboratoire inconnu se distingue d'un laboratoire sans collection : la route en tire deux statuts."""
        res = _q(sa_sync_conn).hal_missing_collections(lab_id=999999, page=1, per_page=50)
        assert res is NoMissingCollections.UNKNOWN_LAB

    def test_returns_empty_when_no_missing(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn, code="LAB-X", hal_collection="COLL-X")
        res = _q(sa_sync_conn).hal_missing_collections(lab_id=lab, page=1, per_page=50)
        assert res is not None
        assert res.total == 0
        assert res.lab_acronym is None  # structure sans acronyme


def _create_hal_contribution(conn, publication, code):
    """Crée une contribution de `publication`, rattachée à une personne créée, dont la contribution source HAL est dans le périmètre et atteint le laboratoire d'acronyme `code`. Renvoie la contribution."""
    lab = _create_lab(conn, code=code, hal_collection=f"COLL-{code}", acronym=code)
    hal_source_record = _source_record(conn, publication, source_id=f"h-{code}")
    hal_source_contribution = insert_source_contribution(conn, hal_source_record, in_perimeter=True)
    contribution = align_source_contributions(
        conn, publication, [(hal_source_contribution, hal_source_record)]
    )
    conn.execute(
        text(
            "UPDATE contributions SET person_id = :person, resolution_mode = 'manual' WHERE id = :g"
        ),
        {"person": insert_person(conn), "g": contribution},
    )
    add_source_contribution_structure(conn, hal_source_contribution, lab)
    return contribution


def _create_address_for_source_contribution(conn, source_contribution_id):
    # Le texte dérivé de la contribution source rend chaque adresse unique (contrainte d'unicité sur `md5(raw_text)`).
    addr_id = insert_address(
        conn, f"addr-{source_contribution_id}", normalized_text=f"addr-{source_contribution_id}"
    )
    insert_source_contribution_address(conn, source_contribution_id, address_id=addr_id)
    return addr_id


def _add_source_contribution(
    conn,
    source_record,
    contribution,
    *,
    source,
    in_perimeter=None,
    address=True,
    author_position=0,
):
    """Aligne dans `contribution` une contribution source de `source_record`, avec une adresse si `address`. Renvoie la contribution source."""
    source_contribution = insert_source_contribution(
        conn,
        source_record,
        source=source,
        in_perimeter=in_perimeter,
        author_position=author_position,
    )
    add_aligned_source_contribution(conn, contribution, source_contribution, source_record)
    if address:
        _create_address_for_source_contribution(conn, source_contribution)
    return source_contribution


def _conflict_ids(conn):
    return [p.id for p in _q(conn).hal_affiliation_conflicts(page=1, per_page=50).publications]


class TestHalAffiliationConflicts:
    """Conflit : la contribution source HAL d'une contribution est dans le périmètre ; ses contributions sources WoS ou OpenAlex donnent une adresse ou un ROR, et sont toutes hors du périmètre."""

    def test_noop_when_no_data(self, sa_sync_conn):
        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert res.total == 0
        assert res.publications == []

    def test_detects_conflict_with_openalex(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-OA")
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-1"
        )
        _add_source_contribution(sa_sync_conn, oa_source_record, contribution, source="openalex")

        assert _conflict_ids(sa_sync_conn) == [publication]

    def test_detects_conflict_with_wos(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-WOS")
        wos_source_record = _source_record(
            sa_sync_conn, publication, source="wos", source_id="WOS:1"
        )
        _add_source_contribution(sa_sync_conn, wos_source_record, contribution, source="wos")

        assert _conflict_ids(sa_sync_conn) == [publication]

    def test_detects_conflict_with_ror_without_address(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-ROR")
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-ror"
        )
        oa_source_contribution = _add_source_contribution(
            sa_sync_conn, oa_source_record, contribution, source="openalex", address=False
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_contribution_rors (source_contribution_id, ror_id) VALUES (:s, '0abcdef00')"
            ),
            {"s": oa_source_contribution},
        )

        assert _conflict_ids(sa_sync_conn) == [publication]

    def test_ignores_openalex_without_affiliation(self, sa_sync_conn):
        # Sans adresse ni ROR, la contribution source OpenAlex ne dit rien de l'affiliation.
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-NOADDR")
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-noaddr"
        )
        _add_source_contribution(
            sa_sync_conn, oa_source_record, contribution, source="openalex", address=False
        )

        assert _conflict_ids(sa_sync_conn) == []

    def test_ignores_affiliation_of_another_author(self, sa_sync_conn):
        # La contribution source OpenAlex de l'auteur placé dans le périmètre par HAL est sans affiliation ; celle d'un autre auteur a une adresse hors du périmètre.
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-OTHER")
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-other"
        )
        _add_source_contribution(
            sa_sync_conn, oa_source_record, contribution, source="openalex", address=False
        )
        other_source_contribution = insert_source_contribution(
            sa_sync_conn, oa_source_record, source="openalex", author_position=1
        )
        align_source_contributions(
            sa_sync_conn, publication, [(other_source_contribution, oa_source_record)]
        )
        _create_address_for_source_contribution(sa_sync_conn, other_source_contribution)

        assert _conflict_ids(sa_sync_conn) == []

    def test_ignores_scanr(self, sa_sync_conn):
        # ScanR moissonne HAL et reproduit ses affiliations : il est exclu de la comparaison.
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-SCANR")
        scanr_source_record = _source_record(
            sa_sync_conn, publication, source="scanr", source_id="sr-1"
        )
        _add_source_contribution(sa_sync_conn, scanr_source_record, contribution, source="scanr")

        assert _conflict_ids(sa_sync_conn) == []

    def test_ignores_when_openalex_confirms(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-CONFIRM")
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-confirm"
        )
        _add_source_contribution(
            sa_sync_conn, oa_source_record, contribution, source="openalex", in_perimeter=True
        )

        assert _conflict_ids(sa_sync_conn) == []

    def test_ignores_when_one_of_wos_openalex_confirms(self, sa_sync_conn):
        # OpenAlex contredit HAL, WoS le confirme.
        publication = insert_publication(sa_sync_conn)
        contribution = _create_hal_contribution(sa_sync_conn, publication, "LAB-MIXED")
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-mixed"
        )
        _add_source_contribution(sa_sync_conn, oa_source_record, contribution, source="openalex")
        wos_source_record = _source_record(
            sa_sync_conn, publication, source="wos", source_id="WOS:mixed"
        )
        _add_source_contribution(
            sa_sync_conn, wos_source_record, contribution, source="wos", in_perimeter=True
        )

        assert _conflict_ids(sa_sync_conn) == []

    def test_requires_wos_or_openalex(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _create_hal_contribution(sa_sync_conn, publication, "LAB-HALONLY")

        assert _conflict_ids(sa_sync_conn) == []

    def test_lists_laboratories_of_conflicting_contributions(self, sa_sync_conn):
        # La seconde contribution est dans le périmètre selon HAL et selon OpenAlex.
        publication = insert_publication(sa_sync_conn)
        conflicting = _create_hal_contribution(sa_sync_conn, publication, "LAB-A")
        confirmed = _create_hal_contribution(sa_sync_conn, publication, "LAB-B")
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-labs"
        )
        _add_source_contribution(sa_sync_conn, oa_source_record, conflicting, source="openalex")
        _add_source_contribution(
            sa_sync_conn,
            oa_source_record,
            confirmed,
            source="openalex",
            in_perimeter=True,
            author_position=1,
        )

        [conflict] = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50).publications
        assert [lab.acronym for lab in conflict.laboratories] == ["LAB-A"]
