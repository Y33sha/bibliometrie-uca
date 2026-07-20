"""Tests d'intégration pour `infrastructure.queries.api.addresses`."""

from sqlalchemy import text

from application.ports.api.addresses_queries import (
    AddressCountriesFilters,
    AddressListFilters,
    StructurePredicate,
    TextPredicate,
)
from infrastructure.queries.api.addresses import PgAddressesQueries
from tests.integration.helpers.authorships import upsert_identity


def _q(conn) -> PgAddressesQueries:
    return PgAddressesQueries(conn)


def _create_structure(conn, code="UCA"):
    row = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:c, 'X', 'universite') RETURNING id"
        ),
        {"c": code},
    ).one()
    return row.id


def _create_address(conn, raw_text="X", countries=None, pub_count=0, suggested_countries=None):
    row = conn.execute(
        text("""
            INSERT INTO addresses
                (raw_text, normalized_text, countries, pub_count, suggested_countries)
            VALUES (:rt, :nt, :c, :pc, :sc) RETURNING id
        """),
        {
            "rt": raw_text,
            "nt": raw_text.lower(),
            "c": countries,
            "pc": pub_count,
            "sc": suggested_countries,
        },
    ).one()
    return row.id


def _link_addr_struct(conn, addr_id, struct_id, *, is_confirmed=None, matched_form_id=None):
    conn.execute(
        text("""
            INSERT INTO address_structures
                (address_id, structure_id, is_confirmed, matched_form_id)
            VALUES (:aid, :sid, :ic, :mfi)
        """),
        {"aid": addr_id, "sid": struct_id, "ic": is_confirmed, "mfi": matched_form_id},
    )


def _ensure_country(conn, code, name="Test"):
    conn.execute(
        text("INSERT INTO countries (code, name) VALUES (:c, :n) ON CONFLICT DO NOTHING"),
        {"c": code, "n": name},
    )


class TestListAddresses:
    def test_lists_detected_and_pending_by_default(self, sa_sync_conn):
        struct = _create_structure(sa_sync_conn)
        # Form pour matched_form_id
        form_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:s, 'x', true) RETURNING id"
            ),
            {"s": struct},
        ).one()
        form_id = form_row.id

        addr_pending = _create_address(sa_sync_conn, raw_text="a-pending")
        _link_addr_struct(sa_sync_conn, addr_pending, struct, matched_form_id=form_id)

        addr_confirmed = _create_address(sa_sync_conn, raw_text="a-confirmed")
        _link_addr_struct(
            sa_sync_conn, addr_confirmed, struct, matched_form_id=form_id, is_confirmed=True
        )

        res = _q(sa_sync_conn).list_addresses(
            structure_id=struct, filters=AddressListFilters(), page=1, per_page=10
        )
        ids = [a.id for a in res.addresses]
        assert addr_pending in ids
        assert addr_confirmed not in ids  # validation=pending → exclut confirmed

    def test_lists_confirmed_only(self, sa_sync_conn):
        struct = _create_structure(sa_sync_conn)
        form_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:s, 'x', true) RETURNING id"
            ),
            {"s": struct},
        ).one()
        form_id = form_row.id
        addr = _create_address(sa_sync_conn, raw_text="A")
        _link_addr_struct(sa_sync_conn, addr, struct, matched_form_id=form_id, is_confirmed=True)

        res = _q(sa_sync_conn).list_addresses(
            structure_id=struct,
            filters=AddressListFilters(validation="confirmed"),
            page=1,
            per_page=10,
        )
        assert any(a.id == addr for a in res.addresses)

    def test_search_filter(self, sa_sync_conn):
        struct = _create_structure(sa_sync_conn)
        form_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:s, 'x', true) RETURNING id"
            ),
            {"s": struct},
        ).one()
        form_id = form_row.id
        a1 = _create_address(sa_sync_conn, raw_text="Université Clermont")
        a2 = _create_address(sa_sync_conn, raw_text="Université Paris")
        _link_addr_struct(sa_sync_conn, a1, struct, matched_form_id=form_id)
        _link_addr_struct(sa_sync_conn, a2, struct, matched_form_id=form_id)

        res = _q(sa_sync_conn).list_addresses(
            structure_id=struct,
            filters=AddressListFilters(
                text_predicates=(TextPredicate(mode="contains", term="Clermont"),)
            ),
            page=1,
            per_page=10,
        )
        ids = [a.id for a in res.addresses]
        assert a1 in ids
        assert a2 not in ids

    def test_text_predicates_combined_and(self, sa_sync_conn):
        # contient « Clermont » ET ne contient pas « Toulouse » → ET entre prédicats.
        scope = _create_structure(sa_sync_conn, code="SCOPE-T")
        a1 = _create_address(sa_sync_conn, raw_text="Université Clermont Auvergne")
        a2 = _create_address(sa_sync_conn, raw_text="Université Clermont Toulouse")

        res = _q(sa_sync_conn).list_addresses(
            structure_id=scope,
            filters=AddressListFilters(
                detected="all",
                validation="all",
                text_predicates=(
                    TextPredicate(mode="contains", term="Clermont"),
                    TextPredicate(mode="not_contains", term="Toulouse"),
                ),
            ),
            page=1,
            per_page=10,
        )
        ids = [a.id for a in res.addresses]
        assert a1 in ids
        assert a2 not in ids


class TestStructurePredicates:
    """Prédicats « structure reconnue » (reconnue = lien pending ou confirmé)."""

    def _form(self, conn, struct_id):
        return (
            conn.execute(
                text(
                    "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                    "VALUES (:s, 'f', true) RETURNING id"
                ),
                {"s": struct_id},
            )
            .one()
            .id
        )

    def test_recognized_matches_pending_and_confirmed_only(self, sa_sync_conn):
        scope = _create_structure(sa_sync_conn, code="SCOPE-R")
        k = _create_structure(sa_sync_conn, code="CNRS-R")
        form_id = self._form(sa_sync_conn, k)

        a_pending = _create_address(sa_sync_conn, raw_text="pending")
        _link_addr_struct(sa_sync_conn, a_pending, k, matched_form_id=form_id)  # détecté, non revu
        a_confirmed = _create_address(sa_sync_conn, raw_text="confirmed")
        _link_addr_struct(sa_sync_conn, a_confirmed, k, is_confirmed=True)  # relié manuel
        a_rejected = _create_address(sa_sync_conn, raw_text="rejected")
        _link_addr_struct(sa_sync_conn, a_rejected, k, matched_form_id=form_id, is_confirmed=False)
        a_none = _create_address(sa_sync_conn, raw_text="none")

        res = _q(sa_sync_conn).list_addresses(
            structure_id=scope,
            filters=AddressListFilters(
                detected="all",
                validation="all",
                structure_predicates=(
                    StructurePredicate(operator="recognized", structure_ids=(k,)),
                ),
            ),
            page=1,
            per_page=50,
        )
        ids = {a.id for a in res.addresses}
        assert {a_pending, a_confirmed} <= ids
        assert a_rejected not in ids
        assert a_none not in ids

    def test_not_recognized_is_complement(self, sa_sync_conn):
        scope = _create_structure(sa_sync_conn, code="SCOPE-N")
        k = _create_structure(sa_sync_conn, code="CNRS-N")
        form_id = self._form(sa_sync_conn, k)

        a_recognized = _create_address(sa_sync_conn, raw_text="rec")
        _link_addr_struct(sa_sync_conn, a_recognized, k, matched_form_id=form_id)
        a_rejected = _create_address(sa_sync_conn, raw_text="rej")
        _link_addr_struct(sa_sync_conn, a_rejected, k, matched_form_id=form_id, is_confirmed=False)
        a_none = _create_address(sa_sync_conn, raw_text="non")

        res = _q(sa_sync_conn).list_addresses(
            structure_id=scope,
            filters=AddressListFilters(
                detected="all",
                validation="all",
                structure_predicates=(
                    StructurePredicate(operator="not_recognized", structure_ids=(k,)),
                ),
            ),
            page=1,
            per_page=50,
        )
        ids = {a.id for a in res.addresses}
        assert a_recognized not in ids
        assert {a_rejected, a_none} <= ids

    def test_recognized_multi_structure_is_or(self, sa_sync_conn):
        scope = _create_structure(sa_sync_conn, code="SCOPE-M")
        k1 = _create_structure(sa_sync_conn, code="CNRS-M")
        k2 = _create_structure(sa_sync_conn, code="INSERM-M")
        f1 = self._form(sa_sync_conn, k1)
        f2 = self._form(sa_sync_conn, k2)

        a_k1 = _create_address(sa_sync_conn, raw_text="k1")
        _link_addr_struct(sa_sync_conn, a_k1, k1, matched_form_id=f1)
        a_k2 = _create_address(sa_sync_conn, raw_text="k2")
        _link_addr_struct(sa_sync_conn, a_k2, k2, matched_form_id=f2)
        a_none = _create_address(sa_sync_conn, raw_text="neither")

        res = _q(sa_sync_conn).list_addresses(
            structure_id=scope,
            filters=AddressListFilters(
                detected="all",
                validation="all",
                structure_predicates=(
                    StructurePredicate(operator="recognized", structure_ids=(k1, k2)),
                ),
            ),
            page=1,
            per_page=50,
        )
        ids = {a.id for a in res.addresses}
        assert {a_k1, a_k2} <= ids
        assert a_none not in ids


class TestGetAddressRawText:
    def test_returns_none_for_missing(self, sa_sync_conn):
        assert _q(sa_sync_conn).get_address_raw_text(999_999) is None

    def test_returns_raw_text(self, sa_sync_conn):
        addr = _create_address(sa_sync_conn, raw_text="rue X")
        assert _q(sa_sync_conn).get_address_raw_text(addr) == "rue X"


class TestGetAddressPublications:
    def test_returns_linked_publications(self, sa_sync_conn):
        pub_row = sa_sync_conn.execute(
            text("""
                INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
                VALUES ('T', 't', 2024, 'article', '10.1/a') RETURNING id
            """)
        ).one()
        pub = pub_row.id
        sd_row = sa_sync_conn.execute(
            text("""
                INSERT INTO source_publications (source, source_id, title, publication_id)
                VALUES ('hal', 'h-1', 'T', :p) RETURNING id
            """),
            {"p": pub},
        ).one()
        sd = sd_row.id
        identity_id = upsert_identity(sa_sync_conn)
        sa_row = sa_sync_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, author_position, identity_id)
                VALUES ('hal', :sd, 0, :iid) RETURNING id
            """),
            {"sd": sd, "iid": identity_id},
        ).one()
        sa_id = sa_row.id
        addr = _create_address(sa_sync_conn, raw_text="rue X")
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
                "VALUES (:sa, :a)"
            ),
            {"sa": sa_id, "a": addr},
        )

        rows = _q(sa_sync_conn).get_address_publications(addr, limit=10)
        assert len(rows) == 1
        assert rows[0].id == pub


class TestGetAddressStructures:
    def test_returns_structures(self, sa_sync_conn):
        struct = _create_structure(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        _link_addr_struct(sa_sync_conn, addr, struct, is_confirmed=True)

        rows = _q(sa_sync_conn).get_address_structures(addr)
        assert len(rows) == 1
        assert rows[0].id == struct

    def test_returns_empty_list_when_no_link(self, sa_sync_conn):
        addr = _create_address(sa_sync_conn)
        rows = _q(sa_sync_conn).get_address_structures(addr)
        assert rows == []


class TestGetStructureLink:
    def test_returns_status(self, sa_sync_conn):
        struct = _create_structure(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        _link_addr_struct(sa_sync_conn, addr, struct, is_confirmed=True)

        link = _q(sa_sync_conn).get_structure_link(addr, struct)
        assert link["is_confirmed"] is True
        assert link["is_detected"] is False

    def test_returns_none_when_no_link(self, sa_sync_conn):
        struct = _create_structure(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        assert _q(sa_sync_conn).get_structure_link(addr, struct) is None


class TestAddressesCountries:
    def test_returns_addresses_with_countries(self, sa_sync_conn):
        _ensure_country(sa_sync_conn, "FR")
        _create_address(sa_sync_conn, raw_text="A", countries=["FR"])
        _create_address(sa_sync_conn, raw_text="B", countries=None)

        res = _q(sa_sync_conn).addresses_countries(
            filters=AddressCountriesFilters(has_country="yes"), page=1, per_page=50
        )
        assert res.total >= 1
        assert all(a.countries is not None for a in res.addresses)

    def test_filters_by_country_code(self, sa_sync_conn):
        _ensure_country(sa_sync_conn, "FR")
        _ensure_country(sa_sync_conn, "US")
        a_fr = _create_address(sa_sync_conn, raw_text="A-fr", countries=["FR"])
        _create_address(sa_sync_conn, raw_text="A-us", countries=["US"])

        res = _q(sa_sync_conn).addresses_countries(
            filters=AddressCountriesFilters(country_code="FR"), page=1, per_page=50
        )
        ids = [a.id for a in res.addresses]
        assert a_fr in ids
        # La facette countries doit être présente
        assert res.country_facets is not None

    def test_suggest_mode_returns_facets(self, sa_sync_conn):
        _ensure_country(sa_sync_conn, "FR")
        _create_address(sa_sync_conn, raw_text="sug", countries=None, suggested_countries=["FR"])
        res = _q(sa_sync_conn).addresses_countries(
            filters=AddressCountriesFilters(suggest=True), page=1, per_page=50
        )
        assert res.suggestion_facets is not None
