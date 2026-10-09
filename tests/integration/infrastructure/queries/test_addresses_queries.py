"""Tests d'intégration pour `infrastructure.read_models.addresses`."""

from sqlalchemy import text

from application.ports.read_models.addresses_queries import (
    AddressCountriesFilters,
    AddressListFilters,
    StructurePredicate,
    TextPredicate,
)
from infrastructure.read_models.addresses import PgAddressesQueries
from tests.integration.helpers.addresses import ensure_country, insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)
from tests.integration.helpers.structures import insert_structure


def _q(conn) -> PgAddressesQueries:
    return PgAddressesQueries(conn)


def _link_addr_struct(conn, addr_id, struct_id, *, is_confirmed=None, matched_form_id=None):
    conn.execute(
        text("""
            INSERT INTO address_structures
                (address_id, structure_id, is_confirmed, matched_form_id)
            VALUES (:aid, :sid, :ic, :mfi)
        """),
        {"aid": addr_id, "sid": struct_id, "ic": is_confirmed, "mfi": matched_form_id},
    )


class TestListAddresses:
    def test_lists_detected_and_pending_by_default(self, sa_sync_conn):
        struct = insert_structure(sa_sync_conn, "UCA", name="X", structure_type="universite")
        # Form pour matched_form_id
        form_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:s, 'x', true) RETURNING id"
            ),
            {"s": struct},
        ).one()
        form_id = form_row.id

        addr_pending = insert_address(sa_sync_conn, "a-pending")
        _link_addr_struct(sa_sync_conn, addr_pending, struct, matched_form_id=form_id)

        addr_confirmed = insert_address(sa_sync_conn, "a-confirmed")
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
        struct = insert_structure(sa_sync_conn, "UCA", name="X", structure_type="universite")
        form_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:s, 'x', true) RETURNING id"
            ),
            {"s": struct},
        ).one()
        form_id = form_row.id
        addr = insert_address(sa_sync_conn, "A")
        _link_addr_struct(sa_sync_conn, addr, struct, matched_form_id=form_id, is_confirmed=True)

        res = _q(sa_sync_conn).list_addresses(
            structure_id=struct,
            filters=AddressListFilters(validation="confirmed"),
            page=1,
            per_page=10,
        )
        assert any(a.id == addr for a in res.addresses)

    def test_search_filter(self, sa_sync_conn):
        struct = insert_structure(sa_sync_conn, "UCA", name="X", structure_type="universite")
        form_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:s, 'x', true) RETURNING id"
            ),
            {"s": struct},
        ).one()
        form_id = form_row.id
        a1 = insert_address(sa_sync_conn, "Université Clermont")
        a2 = insert_address(sa_sync_conn, "Université Paris")
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
        scope = insert_structure(sa_sync_conn, "SCOPE-T", name="X", structure_type="universite")
        a1 = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        a2 = insert_address(sa_sync_conn, "Université Clermont Toulouse")

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
        scope = insert_structure(sa_sync_conn, "SCOPE-R", name="X", structure_type="universite")
        k = insert_structure(sa_sync_conn, "CNRS-R", name="X", structure_type="universite")
        form_id = self._form(sa_sync_conn, k)

        a_pending = insert_address(sa_sync_conn, "pending")
        _link_addr_struct(sa_sync_conn, a_pending, k, matched_form_id=form_id)  # détecté, non revu
        a_confirmed = insert_address(sa_sync_conn, "confirmed")
        _link_addr_struct(sa_sync_conn, a_confirmed, k, is_confirmed=True)  # relié manuel
        a_rejected = insert_address(sa_sync_conn, "rejected")
        _link_addr_struct(sa_sync_conn, a_rejected, k, matched_form_id=form_id, is_confirmed=False)
        a_none = insert_address(sa_sync_conn, "none")

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
        scope = insert_structure(sa_sync_conn, "SCOPE-N", name="X", structure_type="universite")
        k = insert_structure(sa_sync_conn, "CNRS-N", name="X", structure_type="universite")
        form_id = self._form(sa_sync_conn, k)

        a_recognized = insert_address(sa_sync_conn, "rec")
        _link_addr_struct(sa_sync_conn, a_recognized, k, matched_form_id=form_id)
        a_rejected = insert_address(sa_sync_conn, "rej")
        _link_addr_struct(sa_sync_conn, a_rejected, k, matched_form_id=form_id, is_confirmed=False)
        a_none = insert_address(sa_sync_conn, "non")

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
        scope = insert_structure(sa_sync_conn, "SCOPE-M", name="X", structure_type="universite")
        k1 = insert_structure(sa_sync_conn, "CNRS-M", name="X", structure_type="universite")
        k2 = insert_structure(sa_sync_conn, "INSERM-M", name="X", structure_type="universite")
        f1 = self._form(sa_sync_conn, k1)
        f2 = self._form(sa_sync_conn, k2)

        a_k1 = insert_address(sa_sync_conn, "k1")
        _link_addr_struct(sa_sync_conn, a_k1, k1, matched_form_id=f1)
        a_k2 = insert_address(sa_sync_conn, "k2")
        _link_addr_struct(sa_sync_conn, a_k2, k2, matched_form_id=f2)
        a_none = insert_address(sa_sync_conn, "neither")

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
        addr = insert_address(sa_sync_conn, "rue X")
        assert _q(sa_sync_conn).get_address_raw_text(addr) == "rue X"


class TestGetAddressPublications:
    def test_returns_linked_publications(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn, "T", doi="10.1/a")
        sd = insert_source_publication(sa_sync_conn, pub, source_id="h-1", title="T")
        sa_id = insert_signature(sa_sync_conn, sd)
        addr = insert_address(sa_sync_conn, "rue X")
        insert_signature_address(sa_sync_conn, sa_id, address_id=addr)

        rows = _q(sa_sync_conn).get_address_publications(addr, limit=10)
        assert len(rows) == 1
        assert rows[0].id == pub


class TestGetAddressStructures:
    def test_returns_structures(self, sa_sync_conn):
        struct = insert_structure(sa_sync_conn, "UCA", name="X", structure_type="universite")
        addr = insert_address(sa_sync_conn)
        _link_addr_struct(sa_sync_conn, addr, struct, is_confirmed=True)

        rows = _q(sa_sync_conn).get_address_structures(addr)
        assert len(rows) == 1
        assert rows[0].id == struct

    def test_returns_empty_list_when_no_link(self, sa_sync_conn):
        addr = insert_address(sa_sync_conn)
        rows = _q(sa_sync_conn).get_address_structures(addr)
        assert rows == []


class TestGetStructureLink:
    def test_returns_status(self, sa_sync_conn):
        struct = insert_structure(sa_sync_conn, "UCA", name="X", structure_type="universite")
        addr = insert_address(sa_sync_conn)
        _link_addr_struct(sa_sync_conn, addr, struct, is_confirmed=True)

        link = _q(sa_sync_conn).get_structure_link(addr, struct)
        assert link is not None
        assert link.is_confirmed is True
        assert link.is_detected is False

    def test_returns_none_when_no_link(self, sa_sync_conn):
        struct = insert_structure(sa_sync_conn, "UCA", name="X", structure_type="universite")
        addr = insert_address(sa_sync_conn)
        assert _q(sa_sync_conn).get_structure_link(addr, struct) is None


class TestAddressesCountries:
    def test_returns_addresses_with_countries(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "FR")
        insert_address(sa_sync_conn, "A", countries=["FR"])
        insert_address(sa_sync_conn, "B", countries=None)

        res = _q(sa_sync_conn).addresses_countries(
            filters=AddressCountriesFilters(has_country="yes"), page=1, per_page=50
        )
        assert res.total >= 1
        assert all(a.countries is not None for a in res.addresses)

    def test_filters_by_country_code(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "FR")
        ensure_country(sa_sync_conn, "US")
        a_fr = insert_address(sa_sync_conn, "A-fr", countries=["FR"])
        insert_address(sa_sync_conn, "A-us", countries=["US"])

        res = _q(sa_sync_conn).addresses_countries(
            filters=AddressCountriesFilters(country_code="FR"), page=1, per_page=50
        )
        ids = [a.id for a in res.addresses]
        assert a_fr in ids
        # La facette countries doit être présente
        assert res.country_facets is not None

    def test_suggest_mode_returns_facets(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "FR")
        insert_address(sa_sync_conn, "sug", countries=None, suggested_countries=["FR"])
        res = _q(sa_sync_conn).addresses_countries(
            filters=AddressCountriesFilters(suggest=True), page=1, per_page=50
        )
        assert res.suggestion_facets is not None
