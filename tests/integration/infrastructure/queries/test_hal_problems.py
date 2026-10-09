"""Tests d'intégration pour `infrastructure.read_models.hal_problems`."""

from functools import partial

from sqlalchemy import text

from application.ports.read_models.hal_problems_queries import NoMissingCollections
from infrastructure.read_models.hal_problems import PgHalProblemsQueries
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.authorships import insert_authorship
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)
from tests.integration.helpers.structures import add_authorship_structure

# Notice de 2024, de titre « T ».
_notice = partial(insert_source_publication, title="T", pub_year=2024)


def _q(conn) -> PgHalProblemsQueries:
    return PgHalProblemsQueries(conn)


def _create_lab(conn, code="LAB", hal_collection=None):
    row = conn.execute(
        text("""
            INSERT INTO structures (code, name, structure_type, hal_collection)
            VALUES (:c, 'L', 'labo', :col) RETURNING id
        """),
        {"c": code, "col": hal_collection},
    ).one()
    lab_id = row.id
    # Rattache au périmètre persons, désigné en configuration : les lectures HAL scopent
    # au périmètre, pas au type de structure.
    conn.execute(
        text(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', '\"uca\"') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    )
    perim_id = conn.execute(
        text("""
            INSERT INTO perimeters (code, name) VALUES ('uca', 'test persons perimeter')
            ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id
        """)
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO perimeter_structures (perimeter_id, structure_id) "
            "VALUES (:p, :s) ON CONFLICT DO NOTHING"
        ),
        {"p": perim_id, "s": lab_id},
    )
    return lab_id


def _create_hal_sa_with_hal_id(
    conn, *, person_id, hal_person_id, source_id="h-acc", raw_author_name="X"
):
    """Crée un sa HAL portant `hal_person_id` sur son identité."""
    pub = insert_publication(conn, title=f"P-{source_id}", title_normalized=f"p-{source_id}")
    sd = _notice(conn, pub, source_id=source_id)
    insert_signature(
        conn,
        sd,
        person_id=person_id,
        raw_author_name=raw_author_name,
        person_identifiers={"hal_person_id": hal_person_id},
    )


class TestHalDuplicateAccounts:
    def test_detects_person_with_two_hal_accounts(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn)
        _create_hal_sa_with_hal_id(
            sa_sync_conn, person_id=pid, hal_person_id=42, source_id="hal-1", raw_author_name="A"
        )
        _create_hal_sa_with_hal_id(
            sa_sync_conn, person_id=pid, hal_person_id=43, source_id="hal-2", raw_author_name="B"
        )

        res = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50)
        assert res.total >= 1
        ours = next((p for p in res.persons if p.person_id == pid), None)
        assert ours is not None
        assert len(ours.hal_accounts) == 2

    def test_ignores_single_account(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn)
        _create_hal_sa_with_hal_id(sa_sync_conn, person_id=pid, hal_person_id=42, source_id="hal-1")
        res = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50)
        assert not any(p.person_id == pid for p in res.persons)


class TestHalDuplicatePubsByDoi:
    def test_detects_two_hal_deposits_same_doi(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        _notice(sa_sync_conn, pub, source_id="h-1", doi="10.1/shared")
        _notice(sa_sync_conn, pub, source_id="h-2", doi="10.1/shared")

        res = _q(sa_sync_conn).hal_duplicate_pubs_by_doi(page=1, per_page=50)
        assert res.total >= 1
        assert any(len(p.halids) >= 2 for p in res.pairs)

    def test_details_each_pair_of_a_multi_pair_page(self, sa_sync_conn):
        """Le détail des publications se lit par lot : chaque paire de la page reçoit le sien."""
        expected = {}
        for i in (1, 2, 3):
            pub = insert_publication(sa_sync_conn, title=f"Doublon {i}", doi=f"10.1/dup-{i}")
            _notice(sa_sync_conn, pub, source_id=f"h-dup-{i}-a", doi=f"10.1/dup-{i}")
            _notice(sa_sync_conn, pub, source_id=f"h-dup-{i}-b", doi=f"10.1/dup-{i}")
            expected[pub] = (f"Doublon {i}", {f"h-dup-{i}-a", f"h-dup-{i}-b"})

        res = _q(sa_sync_conn).hal_duplicate_pubs_by_doi(page=1, per_page=50)

        assert res.total == 3
        served = {
            p.publication.id: (p.publication.title, {d.halid for d in p.publication.hal_docs})
            for p in res.pairs
        }
        assert served == expected

    def test_noop_without_duplicates(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        _notice(sa_sync_conn, pub, source_id="h-uniq", doi="10.1/u")
        res = _q(sa_sync_conn).hal_duplicate_pubs_by_doi(page=1, per_page=50)
        assert res.total == 0


class TestHalDuplicatePubsByMetadata:
    def test_detects_pair_with_same_title_and_year(self, sa_sync_conn):
        # Titre > 30 chars + même année + même doc_type + taille auteurs ±2
        title = "Article Title That Is Long Enough To Trigger Metadata Detection"
        title_norm = title.lower()
        p1 = insert_publication(sa_sync_conn, title=title, title_normalized=title_norm)
        p2 = insert_publication(sa_sync_conn, title=title, title_normalized=title_norm)
        _notice(sa_sync_conn, p1, source_id="h-meta-1")
        _notice(sa_sync_conn, p2, source_id="h-meta-2")

        res = _q(sa_sync_conn).hal_duplicate_pubs_by_metadata(page=1, per_page=50)
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


def _create_authorship_uca(conn, pub_id, lab_id, position=0):
    authorship_id = insert_authorship(
        conn, pub_id, author_position=position, in_perimeter=True, roles=["author"]
    )
    add_authorship_structure(conn, authorship_id, lab_id)
    return authorship_id


def _create_address_for_sa(conn, sa_id):
    # `raw_text` doit être unique (contrainte sur md5(raw_text)). On dérive
    # depuis sa_id pour permettre plusieurs adresses dans le même test.
    addr_id = insert_address(conn, f"addr-{sa_id}", normalized_text=f"addr-{sa_id}")
    insert_signature_address(conn, sa_id, address_id=addr_id)
    return addr_id


class TestHalAffiliationConflicts:
    """Logique : publi avec ≥1 SP HAL ayant ≥1 authorship in_perimeter,
    ≥1 SP WoS/OpenAlex, et aucune SP WoS/OA n'ayant d'authorship in_perimeter."""

    def test_noop_when_no_data(self, sa_sync_conn):
        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert res.total == 0
        assert res.publications == []

    def test_detects_conflict_with_openalex(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn, title="Conflict OA")
        lab = _create_lab(sa_sync_conn, code="LAB-OA")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-oa-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)
        oa_sd = _notice(sa_sync_conn, pub, source="openalex", source_id="oa-1")
        oa_sa = insert_signature(sa_sync_conn, oa_sd, source="openalex")
        _create_address_for_sa(sa_sync_conn, oa_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub in [p.id for p in res.publications]

    def test_detects_conflict_with_wos(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn, title="Conflict WoS")
        lab = _create_lab(sa_sync_conn, code="LAB-WOS")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-wos-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)
        wos_sd = _notice(sa_sync_conn, pub, source="wos", source_id="WOS:1")
        wos_sa = insert_signature(sa_sync_conn, wos_sd, source="wos")
        _create_address_for_sa(sa_sync_conn, wos_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub in [p.id for p in res.publications]

    def test_ignores_oa_without_address(self, sa_sync_conn):
        # Sans adresse sur les authorships OA, la source n'a pas "examiné"
        # l'affiliation — l'absence d'in_perimeter est du silence, pas un
        # désaveu. Garde-fou contre les faux positifs.
        pub = insert_publication(sa_sync_conn, title="OA no address")
        lab = _create_lab(sa_sync_conn, code="LAB-NOADDR")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-noaddr-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)
        oa_sd = _notice(sa_sync_conn, pub, source="openalex", source_id="oa-noaddr")
        insert_signature(sa_sync_conn, oa_sd, source="openalex")

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_detects_regardless_of_position(self, sa_sync_conn):
        # La nouvelle logique est au niveau publication, pas par position.
        # HAL UCA en pos 0, OA hors-UCA en pos 1 → conflit détecté.
        pub = insert_publication(sa_sync_conn, title="Position independent")
        lab = _create_lab(sa_sync_conn, code="LAB-POS")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-pos-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)
        oa_sd = _notice(sa_sync_conn, pub, source="openalex", source_id="oa-pos")
        oa_sa = insert_signature(sa_sync_conn, oa_sd, source="openalex", author_position=1)
        _create_address_for_sa(sa_sync_conn, oa_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub in [p.id for p in res.publications]

    def test_ignores_scanr(self, sa_sync_conn):
        # ScanR moissonne HAL et reproduit ses affiliations — non informatif,
        # exclu de la comparaison.
        pub = insert_publication(sa_sync_conn, title="ScanR only")
        lab = _create_lab(sa_sync_conn, code="LAB-SCANR")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-scanr-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)
        sr_sd = _notice(sa_sync_conn, pub, source="scanr", source_id="sr-1")
        sr_sa = insert_signature(sa_sync_conn, sr_sd, source="scanr")
        _create_address_for_sa(sa_sync_conn, sr_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_ignores_when_oa_confirms_uca(self, sa_sync_conn):
        # OA atteste aussi UCA → pas de conflit.
        pub = insert_publication(sa_sync_conn, title="OA confirms")
        lab = _create_lab(sa_sync_conn, code="LAB-CONFIRM")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-confirm-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)
        oa_sd = _notice(sa_sync_conn, pub, source="openalex", source_id="oa-confirm")
        oa_sa = insert_signature(sa_sync_conn, oa_sd, source="openalex", in_perimeter=True)
        _create_address_for_sa(sa_sync_conn, oa_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_ignores_when_one_of_wos_oa_confirms(self, sa_sync_conn):
        # OA contredit mais WoS confirme → pas de conflit (la condition NOT EXISTS
        # cherche n'importe quelle SP WoS/OA avec in_perimeter).
        pub = insert_publication(sa_sync_conn, title="Mixed conf")
        lab = _create_lab(sa_sync_conn, code="LAB-MIXED")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-mixed-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)
        oa_sd = _notice(sa_sync_conn, pub, source="openalex", source_id="oa-mixed")
        oa_sa = insert_signature(sa_sync_conn, oa_sd, source="openalex")
        _create_address_for_sa(sa_sync_conn, oa_sa)
        wos_sd = _notice(sa_sync_conn, pub, source="wos", source_id="WOS:mixed")
        wos_sa = insert_signature(sa_sync_conn, wos_sd, source="wos", in_perimeter=True)
        _create_address_for_sa(sa_sync_conn, wos_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_requires_at_least_one_wos_or_oa(self, sa_sync_conn):
        # Publi vue seulement par HAL → pas de comparaison possible, pas un conflit.
        pub = insert_publication(sa_sync_conn, title="HAL only")
        lab = _create_lab(sa_sync_conn, code="LAB-HALONLY")
        hal_sd = _notice(sa_sync_conn, pub, source_id="h-only-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        insert_signature(sa_sync_conn, hal_sd, authorship_id=a_uca, in_perimeter=True)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]
