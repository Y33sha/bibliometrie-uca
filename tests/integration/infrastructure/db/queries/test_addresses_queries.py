"""Tests d'intégration pour `infrastructure.db.queries.addresses` (async)."""

from sqlalchemy import text

from application.ports.addresses_queries import (
    AddressCountriesFilters,
    AddressListFilters,
)
from infrastructure.db.queries.addresses import PgAsyncAddressesQueries


def _q(conn) -> PgAsyncAddressesQueries:
    return PgAsyncAddressesQueries(conn)


async def _create_structure(conn, code="UCA"):
    row = (
        await conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type) "
                "VALUES (:c, 'X', 'universite') RETURNING id"
            ),
            {"c": code},
        )
    ).one()
    return row.id


async def _create_address(
    conn, raw_text="X", countries=None, pub_count=0, suggested_countries=None
):
    row = (
        await conn.execute(
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
        )
    ).one()
    return row.id


async def _link_addr_struct(conn, addr_id, struct_id, *, is_confirmed=None, matched_form_id=None):
    await conn.execute(
        text("""
            INSERT INTO address_structures
                (address_id, structure_id, is_confirmed, matched_form_id)
            VALUES (:aid, :sid, :ic, :mfi)
        """),
        {"aid": addr_id, "sid": struct_id, "ic": is_confirmed, "mfi": matched_form_id},
    )


async def _ensure_country(conn, code, name="Test"):
    await conn.execute(
        text("INSERT INTO countries (code, name) VALUES (:c, :n) ON CONFLICT DO NOTHING"),
        {"c": code, "n": name},
    )


class TestResolveDefaultStructureId:
    async def test_returns_first_root_from_perimeter(self, sa_conn):
        s1 = await _create_structure(sa_conn, code="UCA-1")
        s2 = await _create_structure(sa_conn, code="UCA-2")
        await sa_conn.execute(
            text("INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', :ids)"),
            {"ids": [s1, s2]},
        )
        await sa_conn.execute(
            text(
                "INSERT INTO config (key, value) "
                "VALUES ('perimeter_persons', to_jsonb('uca'::text))"
            )
        )

        resolved = await _q(sa_conn).resolve_default_structure_id()
        assert resolved == s1

    async def test_returns_zero_when_no_perimeter(self, sa_conn):
        assert await _q(sa_conn).resolve_default_structure_id() == 0


class TestListAddresses:
    async def test_lists_detected_and_pending_by_default(self, sa_conn):
        struct = await _create_structure(sa_conn)
        # Form pour matched_form_id
        form_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO structure_name_forms (structure_id, form_text) "
                    "VALUES (:s, 'x') RETURNING id"
                ),
                {"s": struct},
            )
        ).one()
        form_id = form_row.id

        addr_pending = await _create_address(sa_conn, raw_text="a-pending")
        await _link_addr_struct(sa_conn, addr_pending, struct, matched_form_id=form_id)

        addr_confirmed = await _create_address(sa_conn, raw_text="a-confirmed")
        await _link_addr_struct(
            sa_conn, addr_confirmed, struct, matched_form_id=form_id, is_confirmed=True
        )

        res = await _q(sa_conn).list_addresses(
            structure_id=struct, filters=AddressListFilters(), page=1, per_page=10
        )
        ids = [a["id"] for a in res["addresses"]]
        assert addr_pending in ids
        assert addr_confirmed not in ids  # validation=pending → exclut confirmed

    async def test_lists_confirmed_only(self, sa_conn):
        struct = await _create_structure(sa_conn)
        form_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO structure_name_forms (structure_id, form_text) "
                    "VALUES (:s, 'x') RETURNING id"
                ),
                {"s": struct},
            )
        ).one()
        form_id = form_row.id
        addr = await _create_address(sa_conn, raw_text="A")
        await _link_addr_struct(sa_conn, addr, struct, matched_form_id=form_id, is_confirmed=True)

        res = await _q(sa_conn).list_addresses(
            structure_id=struct,
            filters=AddressListFilters(validation="confirmed"),
            page=1,
            per_page=10,
        )
        assert any(a["id"] == addr for a in res["addresses"])

    async def test_search_filter(self, sa_conn):
        struct = await _create_structure(sa_conn)
        form_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO structure_name_forms (structure_id, form_text) "
                    "VALUES (:s, 'x') RETURNING id"
                ),
                {"s": struct},
            )
        ).one()
        form_id = form_row.id
        a1 = await _create_address(sa_conn, raw_text="Université Clermont")
        a2 = await _create_address(sa_conn, raw_text="Université Paris")
        await _link_addr_struct(sa_conn, a1, struct, matched_form_id=form_id)
        await _link_addr_struct(sa_conn, a2, struct, matched_form_id=form_id)

        res = await _q(sa_conn).list_addresses(
            structure_id=struct,
            filters=AddressListFilters(search="Clermont"),
            page=1,
            per_page=10,
        )
        ids = [a["id"] for a in res["addresses"]]
        assert a1 in ids
        assert a2 not in ids


class TestGetAddressBasic:
    async def test_returns_none_for_missing(self, sa_conn):
        assert await _q(sa_conn).get_address_basic(999_999) is None

    async def test_returns_address(self, sa_conn):
        addr = await _create_address(sa_conn, raw_text="rue X")
        row = await _q(sa_conn).get_address_basic(addr)
        assert row["id"] == addr
        assert row["raw_text"] == "rue X"


class TestGetAddressPublications:
    async def test_returns_linked_publications(self, sa_conn):
        pub_row = (
            await sa_conn.execute(
                text("""
                    INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
                    VALUES ('T', 't', 2024, 'article', '10.1/a') RETURNING id
                """)
            )
        ).one()
        pub = pub_row.id
        sd_row = (
            await sa_conn.execute(
                text("""
                    INSERT INTO source_publications (source, source_id, title, publication_id)
                    VALUES ('hal', 'h-1', 'T', :p) RETURNING id
                """),
                {"p": pub},
            )
        ).one()
        sd = sd_row.id
        sp_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO source_persons (source, source_id, full_name) "
                    "VALUES ('hal', 'sp-1', 'X') RETURNING id"
                )
            )
        ).one()
        sp = sp_row.id
        sa_row = (
            await sa_conn.execute(
                text("""
                    INSERT INTO source_authorships
                        (source, source_publication_id, source_person_id, author_position)
                    VALUES ('hal', :sd, :sp, 0) RETURNING id
                """),
                {"sd": sd, "sp": sp},
            )
        ).one()
        sa_id = sa_row.id
        addr = await _create_address(sa_conn, raw_text="rue X")
        await sa_conn.execute(
            text(
                "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
                "VALUES (:sa, :a)"
            ),
            {"sa": sa_id, "a": addr},
        )

        rows = await _q(sa_conn).get_address_publications(addr, limit=10)
        assert len(rows) == 1
        assert rows[0]["id"] == pub


class TestGetAddressStructures:
    async def test_returns_structures(self, sa_conn):
        struct = await _create_structure(sa_conn)
        addr = await _create_address(sa_conn)
        await _link_addr_struct(sa_conn, addr, struct, is_confirmed=True)

        rows = await _q(sa_conn).get_address_structures(addr)
        assert len(rows) == 1
        assert rows[0]["id"] == struct

    async def test_returns_empty_list_when_no_link(self, sa_conn):
        addr = await _create_address(sa_conn)
        rows = await _q(sa_conn).get_address_structures(addr)
        assert rows == []


class TestGetStructureLink:
    async def test_returns_status(self, sa_conn):
        struct = await _create_structure(sa_conn)
        addr = await _create_address(sa_conn)
        await _link_addr_struct(sa_conn, addr, struct, is_confirmed=True)

        link = await _q(sa_conn).get_structure_link(addr, struct)
        assert link["is_confirmed"] is True
        assert link["is_detected"] is False

    async def test_returns_none_when_no_link(self, sa_conn):
        struct = await _create_structure(sa_conn)
        addr = await _create_address(sa_conn)
        assert await _q(sa_conn).get_structure_link(addr, struct) is None


class TestCountryCheckers:
    async def test_list_countries_sorts_xx_first(self, sa_conn):
        await _ensure_country(sa_conn, "FR", "France")
        await _ensure_country(sa_conn, "xx", "Inconnu")

        rows = await _q(sa_conn).list_countries()
        codes = [r["code"].strip() for r in rows]
        # Tri `(code = 'xx') DESC, name` : TRUE > FALSE → 'xx' arrive en tête
        assert codes[0] == "xx"
        assert "FR" in codes

    async def test_country_exists(self, sa_conn):
        await _ensure_country(sa_conn, "FR")
        assert await _q(sa_conn).country_exists("FR") is True
        assert await _q(sa_conn).country_exists("ZZ") is False

    async def test_address_exists(self, sa_conn):
        addr = await _create_address(sa_conn)
        assert await _q(sa_conn).address_exists(addr) is True
        assert await _q(sa_conn).address_exists(999_999) is False


class TestAddressesCountries:
    async def test_returns_addresses_with_countries(self, sa_conn):
        await _ensure_country(sa_conn, "FR")
        await _create_address(sa_conn, raw_text="A", countries=["FR"])
        await _create_address(sa_conn, raw_text="B", countries=None)

        res = await _q(sa_conn).addresses_countries(
            filters=AddressCountriesFilters(has_country="yes"), page=1, per_page=50
        )
        assert res["total"] >= 1
        assert all(a["countries"] is not None for a in res["addresses"])

    async def test_filters_by_country_code(self, sa_conn):
        await _ensure_country(sa_conn, "FR")
        await _ensure_country(sa_conn, "US")
        a_fr = await _create_address(sa_conn, raw_text="A-fr", countries=["FR"])
        await _create_address(sa_conn, raw_text="A-us", countries=["US"])

        res = await _q(sa_conn).addresses_countries(
            filters=AddressCountriesFilters(country_code="FR"), page=1, per_page=50
        )
        ids = [a["id"] for a in res["addresses"]]
        assert a_fr in ids
        # La facette countries doit être présente
        assert "country_facets" in res

    async def test_suggest_mode_returns_facets(self, sa_conn):
        await _ensure_country(sa_conn, "FR")
        await _create_address(sa_conn, raw_text="sug", countries=None, suggested_countries=["FR"])
        res = await _q(sa_conn).addresses_countries(
            filters=AddressCountriesFilters(suggest=True), page=1, per_page=50
        )
        assert "suggestion_facets" in res


class TestSuggestCountries:
    async def test_returns_suggestions_and_without_country(self, sa_conn):
        await _ensure_country(sa_conn, "FR")
        await _create_address(sa_conn, raw_text="With", countries=["FR"])
        await _create_address(sa_conn, raw_text="Without", countries=None)

        res = await _q(sa_conn).suggest_countries(search="")
        assert any(s["code"] == "FR" for s in res["suggestions"])
        assert res["without_country"] >= 1

    async def test_filters_by_search(self, sa_conn):
        await _ensure_country(sa_conn, "FR")
        await _create_address(sa_conn, raw_text="Match", countries=["FR"])
        await _create_address(sa_conn, raw_text="Nope", countries=["FR"])

        res = await _q(sa_conn).suggest_countries(search="Match")
        assert any(s["code"] == "FR" for s in res["suggestions"])
