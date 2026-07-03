"""Tests d'intégration pour `infrastructure.queries.api.hal_problems`."""

from sqlalchemy import text

from infrastructure.queries.api.hal_problems import PgHalProblemsQueries
from tests.integration.helpers.authorships import upsert_identity
from tests.integration.helpers.structures import add_authorship_structure


def _q(conn) -> PgHalProblemsQueries:
    return PgHalProblemsQueries(conn)


def _create_pub(conn, title="T", doi=None, pub_year=2024, title_normalized=None):
    row = conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
            VALUES (:t, :tn, :y, 'article', :doi) RETURNING id
        """),
        {"t": title, "tn": title_normalized or title.lower(), "y": pub_year, "doi": doi},
    ).one()
    return row.id


def _create_hal_sd(
    conn, pub_id, source_id, doi=None, hal_collections=None, pub_year=2024, title="T"
):
    row = conn.execute(
        text("""
            INSERT INTO source_publications
                (source, source_id, title, publication_id, doi, hal_collections, pub_year)
            VALUES ('hal', :sid, :t, :p, :doi, :cols, :y) RETURNING id
        """),
        {
            "sid": source_id,
            "t": title,
            "p": pub_id,
            "doi": doi,
            "cols": hal_collections,
            "y": pub_year,
        },
    ).one()
    return row.id


def _create_lab(conn, code="LAB", hal_collection=None):
    row = conn.execute(
        text("""
            INSERT INTO structures (code, name, structure_type, hal_collection)
            VALUES (:c, 'L', 'labo', :col) RETURNING id
        """),
        {"c": code, "col": hal_collection},
    ).one()
    return row.id


def _create_person(conn, last="A", first="Z"):
    row = conn.execute(
        text("""
            INSERT INTO persons
                (last_name, first_name, last_name_normalized, first_name_normalized)
            VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id
        """),
        {"l": last, "f": first},
    ).one()
    return row.id


def _create_hal_sa_with_hal_id(
    conn, *, person_id, hal_person_id, source_id="h-acc", raw_author_name="X"
):
    """Crée un sa HAL portant `hal_person_id` sur son identité."""
    pub = _create_pub(conn, title=f"P-{source_id}", title_normalized=f"p-{source_id}")
    sd = _create_hal_sd(conn, pub, source_id=source_id)
    identity_id = upsert_identity(conn, person_identifiers={"hal_person_id": hal_person_id})
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, person_id,
                 raw_author_name, identity_id)
            VALUES ('hal', :sd, 0, :pid, :raw, :iid)
        """),
        {"sd": sd, "pid": person_id, "raw": raw_author_name, "iid": identity_id},
    )


class TestHalDuplicateAccounts:
    def test_detects_person_with_two_hal_accounts(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
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
        pid = _create_person(sa_sync_conn)
        _create_hal_sa_with_hal_id(sa_sync_conn, person_id=pid, hal_person_id=42, source_id="hal-1")
        res = _q(sa_sync_conn).hal_duplicate_accounts(page=1, per_page=50)
        assert not any(p.person_id == pid for p in res.persons)


class TestHalDuplicatePubsByDoi:
    def test_detects_two_hal_deposits_same_doi(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        _create_hal_sd(sa_sync_conn, pub, "h-1", doi="10.1/shared")
        _create_hal_sd(sa_sync_conn, pub, "h-2", doi="10.1/shared")

        res = _q(sa_sync_conn).hal_duplicate_pubs_by_doi(page=1, per_page=50)
        assert res.total >= 1
        assert any(len(p.halids) >= 2 for p in res.pairs)

    def test_noop_without_duplicates(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        _create_hal_sd(sa_sync_conn, pub, "h-uniq", doi="10.1/u")
        res = _q(sa_sync_conn).hal_duplicate_pubs_by_doi(page=1, per_page=50)
        assert res.total == 0


class TestHalDuplicatePubsByMetadata:
    def test_detects_pair_with_same_title_and_year(self, sa_sync_conn):
        # Titre > 30 chars + même année + même doc_type + taille auteurs ±2
        title = "Article Title That Is Long Enough To Trigger Metadata Detection"
        title_norm = title.lower()
        p1 = _create_pub(sa_sync_conn, title=title, title_normalized=title_norm)
        p2 = _create_pub(sa_sync_conn, title=title, title_normalized=title_norm)
        _create_hal_sd(sa_sync_conn, p1, "h-meta-1")
        _create_hal_sd(sa_sync_conn, p2, "h-meta-2")

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
    def test_returns_none_for_lab_without_collection(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn, code="LAB-NO-COL", hal_collection=None)
        res = _q(sa_sync_conn).hal_missing_collections(lab_id=lab, page=1, per_page=50)
        assert res is None

    def test_returns_empty_when_no_missing(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn, code="LAB-X", hal_collection="COLL-X")
        res = _q(sa_sync_conn).hal_missing_collections(lab_id=lab, page=1, per_page=50)
        assert res is not None
        assert res.total == 0
        assert res.lab_acronym is None  # structure sans acronyme


def _create_other_sd(conn, pub_id, source, source_id, pub_year=2024, title="T"):
    row = conn.execute(
        text("""
            INSERT INTO source_publications
                (source, source_id, title, publication_id, pub_year)
            VALUES (:src, :sid, :t, :p, :y) RETURNING id
        """),
        {"src": source, "sid": source_id, "t": title, "p": pub_id, "y": pub_year},
    ).one()
    return row.id


def _create_authorship_uca(conn, pub_id, lab_id, position=0):
    row = conn.execute(
        text("""
            INSERT INTO authorships
                (publication_id, author_position, in_perimeter, roles)
            VALUES (:p, :pos, TRUE, ARRAY['author']) RETURNING id
        """),
        {"p": pub_id, "pos": position},
    ).one()
    add_authorship_structure(conn, row.id, lab_id)
    return row.id


def _create_source_authorship(conn, source, sd_id, position, *, in_perimeter, authorship_id=None):
    row = conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, in_perimeter, authorship_id,
                 identity_id)
            VALUES (:src, :sd, :pos, :inp, :aid, :iid) RETURNING id
        """),
        {
            "src": source,
            "sd": sd_id,
            "pos": position,
            "inp": in_perimeter,
            "aid": authorship_id,
            "iid": upsert_identity(conn),
        },
    ).one()
    return row.id


def _create_address_for_sa(conn, sa_id):
    # `raw_text` doit être unique (contrainte sur md5(raw_text)). On dérive
    # depuis sa_id pour permettre plusieurs adresses dans le même test.
    addr_id = conn.execute(
        text("INSERT INTO addresses (raw_text, normalized_text) VALUES (:raw, :norm) RETURNING id"),
        {"raw": f"addr-{sa_id}", "norm": f"addr-{sa_id}"},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
            "VALUES (:sa, :a)"
        ),
        {"sa": sa_id, "a": addr_id},
    )
    return addr_id


class TestHalAffiliationConflicts:
    """Logique : publi avec ≥1 SP HAL ayant ≥1 authorship in_perimeter,
    ≥1 SP WoS/OpenAlex, et aucune SP WoS/OA n'ayant d'authorship in_perimeter."""

    def test_noop_when_no_data(self, sa_sync_conn):
        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert res.total == 0
        assert res.publications == []

    def test_detects_conflict_with_openalex(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn, title="Conflict OA")
        lab = _create_lab(sa_sync_conn, code="LAB-OA")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-oa-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = _create_other_sd(sa_sync_conn, pub, "openalex", "oa-1")
        oa_sa = _create_source_authorship(sa_sync_conn, "openalex", oa_sd, 0, in_perimeter=False)
        _create_address_for_sa(sa_sync_conn, oa_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub in [p.id for p in res.publications]

    def test_detects_conflict_with_wos(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn, title="Conflict WoS")
        lab = _create_lab(sa_sync_conn, code="LAB-WOS")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-wos-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        wos_sd = _create_other_sd(sa_sync_conn, pub, "wos", "WOS:1")
        wos_sa = _create_source_authorship(sa_sync_conn, "wos", wos_sd, 0, in_perimeter=False)
        _create_address_for_sa(sa_sync_conn, wos_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub in [p.id for p in res.publications]

    def test_ignores_oa_without_address(self, sa_sync_conn):
        # Sans adresse sur les authorships OA, la source n'a pas "examiné"
        # l'affiliation — l'absence d'in_perimeter est du silence, pas un
        # désaveu. Garde-fou contre les faux positifs.
        pub = _create_pub(sa_sync_conn, title="OA no address")
        lab = _create_lab(sa_sync_conn, code="LAB-NOADDR")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-noaddr-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = _create_other_sd(sa_sync_conn, pub, "openalex", "oa-noaddr")
        _create_source_authorship(sa_sync_conn, "openalex", oa_sd, 0, in_perimeter=False)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_detects_regardless_of_position(self, sa_sync_conn):
        # La nouvelle logique est au niveau publication, pas par position.
        # HAL UCA en pos 0, OA hors-UCA en pos 1 → conflit détecté.
        pub = _create_pub(sa_sync_conn, title="Position independent")
        lab = _create_lab(sa_sync_conn, code="LAB-POS")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-pos-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = _create_other_sd(sa_sync_conn, pub, "openalex", "oa-pos")
        oa_sa = _create_source_authorship(sa_sync_conn, "openalex", oa_sd, 1, in_perimeter=False)
        _create_address_for_sa(sa_sync_conn, oa_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub in [p.id for p in res.publications]

    def test_ignores_scanr(self, sa_sync_conn):
        # ScanR moissonne HAL et reproduit ses affiliations — non informatif,
        # exclu de la comparaison.
        pub = _create_pub(sa_sync_conn, title="ScanR only")
        lab = _create_lab(sa_sync_conn, code="LAB-SCANR")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-scanr-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        sr_sd = _create_other_sd(sa_sync_conn, pub, "scanr", "sr-1")
        sr_sa = _create_source_authorship(sa_sync_conn, "scanr", sr_sd, 0, in_perimeter=False)
        _create_address_for_sa(sa_sync_conn, sr_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_ignores_when_oa_confirms_uca(self, sa_sync_conn):
        # OA atteste aussi UCA → pas de conflit.
        pub = _create_pub(sa_sync_conn, title="OA confirms")
        lab = _create_lab(sa_sync_conn, code="LAB-CONFIRM")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-confirm-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = _create_other_sd(sa_sync_conn, pub, "openalex", "oa-confirm")
        oa_sa = _create_source_authorship(sa_sync_conn, "openalex", oa_sd, 0, in_perimeter=True)
        _create_address_for_sa(sa_sync_conn, oa_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_ignores_when_one_of_wos_oa_confirms(self, sa_sync_conn):
        # OA contredit mais WoS confirme → pas de conflit (la condition NOT EXISTS
        # cherche n'importe quelle SP WoS/OA avec in_perimeter).
        pub = _create_pub(sa_sync_conn, title="Mixed conf")
        lab = _create_lab(sa_sync_conn, code="LAB-MIXED")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-mixed-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = _create_other_sd(sa_sync_conn, pub, "openalex", "oa-mixed")
        oa_sa = _create_source_authorship(sa_sync_conn, "openalex", oa_sd, 0, in_perimeter=False)
        _create_address_for_sa(sa_sync_conn, oa_sa)
        wos_sd = _create_other_sd(sa_sync_conn, pub, "wos", "WOS:mixed")
        wos_sa = _create_source_authorship(sa_sync_conn, "wos", wos_sd, 0, in_perimeter=True)
        _create_address_for_sa(sa_sync_conn, wos_sa)

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]

    def test_requires_at_least_one_wos_or_oa(self, sa_sync_conn):
        # Publi vue seulement par HAL → pas de comparaison possible, pas un conflit.
        pub = _create_pub(sa_sync_conn, title="HAL only")
        lab = _create_lab(sa_sync_conn, code="LAB-HALONLY")
        hal_sd = _create_hal_sd(sa_sync_conn, pub, "h-only-1")
        a_uca = _create_authorship_uca(sa_sync_conn, pub, lab, position=0)
        _create_source_authorship(
            sa_sync_conn, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )

        res = _q(sa_sync_conn).hal_affiliation_conflicts(page=1, per_page=50)
        assert pub not in [p.id for p in res.publications]
