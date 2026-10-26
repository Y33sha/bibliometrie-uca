"""Tests d'intégration pour `infrastructure.read_models.hal_problems.queries`."""

from functools import partial

from sqlalchemy import text

from infrastructure.read_models.hal_problems.models import NoMissingCollections
from infrastructure.read_models.hal_problems.queries import HalProblemsQueries
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.config import set_config
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import (
    add_contribution_structure,
    add_to_perimeter,
    insert_structure,
)

# Enregistrement source de 2024, de titre « T ».
_source_record = partial(insert_source_record, title="T", publication_year=2024)


def _q(conn) -> HalProblemsQueries:
    return HalProblemsQueries(conn)


def _create_lab(conn, code="LAB", hal_collection=None):
    lab_id = insert_structure(conn, code, name="L", hal_collection=hal_collection)
    # Rattache au périmètre persons, désigné en configuration : les lectures HAL scopent
    # au périmètre, pas au type de structure.
    set_config(conn, "perimeter_persons", "uca")
    add_to_perimeter(conn, lab_id, code="uca", name="test persons perimeter")
    return lab_id


def _create_hal_source_contribution_with_hal_id(
    conn, *, person_id, hal_person_id, source_id="h-acc", raw_author_name="X"
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

    def test_ignores_single_account(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn)
        _attribute_hal_account(sa_sync_conn, pid, 42)
        res = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50)
        assert res.total == 0

    def test_ignores_rejected_attribution(self, sa_sync_conn):
        """Le compte rejeté pour la personne figure dans ses contributions : publication mal attribuée, hors du périmètre de la page."""
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
        """Des dépôts hors périmètre, sans publication, partagent un DOI."""
        _source_record(sa_sync_conn, None, source_id="h-out-1", doi="10.1/out")
        _source_record(sa_sync_conn, None, source_id="h-out-2", doi="10.1/out")
        res = _q(sa_sync_conn).hal_duplicate_publications_by_doi(page=1, per_page=50)
        assert res.total == 0
        assert res.pairs == []


class TestHalDuplicatePublicationsByMetadata:
    def test_detects_pair_with_same_title_and_year(self, sa_sync_conn):
        # Titre > 30 chars + même année + même doc_type + taille auteurs ±2
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
        """Les deux absences sont distinctes : le router en tire deux statuts."""
        res = _q(sa_sync_conn).hal_missing_collections(lab_id=999999, page=1, per_page=50)
        assert res is NoMissingCollections.UNKNOWN_LAB

    def test_returns_empty_when_no_missing(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn, code="LAB-X", hal_collection="COLL-X")
        res = _q(sa_sync_conn).hal_missing_collections(lab_id=lab, page=1, per_page=50)
        assert res is not None
        assert res.total == 0
        assert res.lab_acronym is None  # structure sans acronyme


def _create_contribution_uca(conn, publication_id, lab_id, position=0):
    """Contribution du périmètre rattachée à `lab_id`. Retourne sa personne, rattachée aux contributions sources qui l'attestent."""
    person_id = insert_person(conn)
    contribution_id = insert_contribution(
        conn,
        publication_id,
        person_id=person_id,
        author_position=position,
        in_perimeter=True,
        roles=["author"],
    )
    add_contribution_structure(conn, contribution_id, lab_id)
    return person_id


def _create_address_for_source_contribution(conn, source_contribution_id):
    # `raw_text` doit être unique (contrainte sur md5(raw_text)). On dérive
    # depuis source_contribution_id pour permettre plusieurs adresses dans le même test.
    addr_id = insert_address(
        conn, f"addr-{source_contribution_id}", normalized_text=f"addr-{source_contribution_id}"
    )
    insert_source_contribution_address(conn, source_contribution_id, address_id=addr_id)
    return addr_id


class TestHalAffiliationConflicts:
    """Logique : publi avec ≥1 enregistrement source HAL ayant ≥1 contribution in_perimeter,
    ≥1 enregistrement source WoS/OpenAlex, et aucun enregistrement source WoS/OA n'ayant de contribution in_perimeter."""

    def test_noop_when_no_data(self, sa_sync_conn):
        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert res.total == 0
        assert res.publications == []

    def test_detects_conflict_with_openalex(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, title="Conflict OA")
        lab = _create_lab(sa_sync_conn, code="LAB-OA")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-oa-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-1"
        )
        oa_source_contribution = insert_source_contribution(
            sa_sync_conn, oa_source_record, source="openalex"
        )
        _create_address_for_source_contribution(sa_sync_conn, oa_source_contribution)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication in [p.id for p in res.publications]

    def test_detects_conflict_with_wos(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, title="Conflict WoS")
        lab = _create_lab(sa_sync_conn, code="LAB-WOS")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-wos-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)
        wos_source_record = _source_record(
            sa_sync_conn, publication, source="wos", source_id="WOS:1"
        )
        wos_source_contribution = insert_source_contribution(
            sa_sync_conn, wos_source_record, source="wos"
        )
        _create_address_for_source_contribution(sa_sync_conn, wos_source_contribution)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication in [p.id for p in res.publications]

    def test_ignores_oa_without_address(self, sa_sync_conn):
        # Sans adresse sur les contributions OA, la source n'a pas "examiné"
        # l'affiliation — l'absence d'in_perimeter est du silence, pas un
        # désaveu. Garde-fou contre les faux positifs.
        publication = insert_publication(sa_sync_conn, title="OA no address")
        lab = _create_lab(sa_sync_conn, code="LAB-NOADDR")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-noaddr-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-noaddr"
        )
        insert_source_contribution(sa_sync_conn, oa_source_record, source="openalex")

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication not in [p.id for p in res.publications]

    def test_detects_regardless_of_position(self, sa_sync_conn):
        # La nouvelle logique est au niveau publication, pas par position.
        # HAL UCA en pos 0, OA hors-UCA en pos 1 → conflit détecté.
        publication = insert_publication(sa_sync_conn, title="Position independent")
        lab = _create_lab(sa_sync_conn, code="LAB-POS")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-pos-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-pos"
        )
        oa_source_contribution = insert_source_contribution(
            sa_sync_conn, oa_source_record, source="openalex", author_position=1
        )
        _create_address_for_source_contribution(sa_sync_conn, oa_source_contribution)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication in [p.id for p in res.publications]

    def test_ignores_scanr(self, sa_sync_conn):
        # ScanR moissonne HAL et reproduit ses affiliations — non informatif,
        # exclu de la comparaison.
        publication = insert_publication(sa_sync_conn, title="ScanR only")
        lab = _create_lab(sa_sync_conn, code="LAB-SCANR")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-scanr-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)
        scanr_source_record = _source_record(
            sa_sync_conn, publication, source="scanr", source_id="sr-1"
        )
        scanr_source_contribution = insert_source_contribution(
            sa_sync_conn, scanr_source_record, source="scanr"
        )
        _create_address_for_source_contribution(sa_sync_conn, scanr_source_contribution)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication not in [p.id for p in res.publications]

    def test_ignores_when_oa_confirms_uca(self, sa_sync_conn):
        # OA atteste aussi UCA → pas de conflit.
        publication = insert_publication(sa_sync_conn, title="OA confirms")
        lab = _create_lab(sa_sync_conn, code="LAB-CONFIRM")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-confirm-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-confirm"
        )
        oa_source_contribution = insert_source_contribution(
            sa_sync_conn, oa_source_record, source="openalex", in_perimeter=True
        )
        _create_address_for_source_contribution(sa_sync_conn, oa_source_contribution)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication not in [p.id for p in res.publications]

    def test_ignores_when_one_of_wos_oa_confirms(self, sa_sync_conn):
        # OA contredit mais WoS confirme → pas de conflit (la condition NOT EXISTS
        # cherche n'importe quelle enregistrement source WoS/OA avec in_perimeter).
        publication = insert_publication(sa_sync_conn, title="Mixed conf")
        lab = _create_lab(sa_sync_conn, code="LAB-MIXED")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-mixed-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-mixed"
        )
        oa_source_contribution = insert_source_contribution(
            sa_sync_conn, oa_source_record, source="openalex"
        )
        _create_address_for_source_contribution(sa_sync_conn, oa_source_contribution)
        wos_source_record = _source_record(
            sa_sync_conn, publication, source="wos", source_id="WOS:mixed"
        )
        wos_source_contribution = insert_source_contribution(
            sa_sync_conn, wos_source_record, source="wos", in_perimeter=True
        )
        _create_address_for_source_contribution(sa_sync_conn, wos_source_contribution)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication not in [p.id for p in res.publications]

    def test_requires_at_least_one_wos_or_oa(self, sa_sync_conn):
        # Publi vue seulement par HAL → pas de comparaison possible, pas un conflit.
        publication = insert_publication(sa_sync_conn, title="HAL only")
        lab = _create_lab(sa_sync_conn, code="LAB-HALONLY")
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="h-only-1")
        _create_contribution_uca(sa_sync_conn, publication, lab, position=0)
        insert_source_contribution(sa_sync_conn, hal_source_record, in_perimeter=True)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert publication not in [p.id for p in res.publications]
