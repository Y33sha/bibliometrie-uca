"""Tests d'intégration pour `infrastructure.db.queries.addresses` (§2.12 : async)."""

from infrastructure.db.queries.addresses import (
    AddressCountriesFilters,
    AddressListFilters,
    address_exists,
    addresses_countries,
    country_exists,
    get_address_basic,
    get_address_publications,
    get_address_structures,
    get_structure_link,
    list_addresses,
    list_countries,
    resolve_default_structure_id,
    suggest_countries,
)


async def _create_structure(db, code="UCA"):
    await db.execute(
        "INSERT INTO structures (code, name, structure_type) VALUES (%s, 'X', 'universite') RETURNING id",
        (code,),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_address(db, raw_text="X", countries=None, pub_count=0, suggested_countries=None):
    await db.execute(
        """
        INSERT INTO addresses (raw_text, normalized_text, countries, pub_count, suggested_countries)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (raw_text, raw_text.lower(), countries, pub_count, suggested_countries),
    )
    row = await db.fetchone()
    return row["id"]


async def _link_addr_struct(db, addr_id, struct_id, *, is_confirmed=None, matched_form_id=None):
    await db.execute(
        """
        INSERT INTO address_structures (address_id, structure_id, is_confirmed, matched_form_id)
        VALUES (%s, %s, %s, %s)
        """,
        (addr_id, struct_id, is_confirmed, matched_form_id),
    )


async def _ensure_country(db, code, name="Test"):
    await db.execute(
        "INSERT INTO countries (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (code, name),
    )


class TestResolveDefaultStructureId:
    async def test_returns_first_root_from_perimeter(self, async_db):
        s1 = await _create_structure(async_db, code="UCA-1")
        s2 = await _create_structure(async_db, code="UCA-2")
        await async_db.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', %s)",
            ([s1, s2],),
        )
        await async_db.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', to_jsonb('uca'::text))"
        )

        resolved = await resolve_default_structure_id(async_db)
        assert resolved == s1

    async def test_returns_zero_when_no_perimeter(self, async_db):
        assert await resolve_default_structure_id(async_db) == 0


class TestListAddresses:
    async def test_lists_detected_and_pending_by_default(self, async_db):
        struct = await _create_structure(async_db)
        # Form pour matched_form_id
        await async_db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'x') RETURNING id",
            (struct,),
        )
        form_id = (await async_db.fetchone())["id"]

        addr_pending = await _create_address(async_db, raw_text="a-pending")
        await _link_addr_struct(async_db, addr_pending, struct, matched_form_id=form_id)

        addr_confirmed = await _create_address(async_db, raw_text="a-confirmed")
        await _link_addr_struct(
            async_db, addr_confirmed, struct, matched_form_id=form_id, is_confirmed=True
        )

        res = await list_addresses(
            async_db, structure_id=struct, filters=AddressListFilters(), page=1, per_page=10
        )
        ids = [a["id"] for a in res["addresses"]]
        assert addr_pending in ids
        assert addr_confirmed not in ids  # validation=pending → exclut confirmed

    async def test_lists_confirmed_only(self, async_db):
        struct = await _create_structure(async_db)
        await async_db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'x') RETURNING id",
            (struct,),
        )
        form_id = (await async_db.fetchone())["id"]
        addr = await _create_address(async_db, raw_text="A")
        await _link_addr_struct(async_db, addr, struct, matched_form_id=form_id, is_confirmed=True)

        res = await list_addresses(
            async_db,
            structure_id=struct,
            filters=AddressListFilters(validation="confirmed"),
            page=1,
            per_page=10,
        )
        assert any(a["id"] == addr for a in res["addresses"])

    async def test_search_filter(self, async_db):
        struct = await _create_structure(async_db)
        await async_db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'x') RETURNING id",
            (struct,),
        )
        form_id = (await async_db.fetchone())["id"]
        a1 = await _create_address(async_db, raw_text="Université Clermont")
        a2 = await _create_address(async_db, raw_text="Université Paris")
        await _link_addr_struct(async_db, a1, struct, matched_form_id=form_id)
        await _link_addr_struct(async_db, a2, struct, matched_form_id=form_id)

        res = await list_addresses(
            async_db,
            structure_id=struct,
            filters=AddressListFilters(search="Clermont"),
            page=1,
            per_page=10,
        )
        ids = [a["id"] for a in res["addresses"]]
        assert a1 in ids
        assert a2 not in ids


class TestGetAddressBasic:
    async def test_returns_none_for_missing(self, async_db):
        assert await get_address_basic(async_db, 999_999) is None

    async def test_returns_address(self, async_db):
        addr = await _create_address(async_db, raw_text="rue X")
        row = await get_address_basic(async_db, addr)
        assert row["id"] == addr
        assert row["raw_text"] == "rue X"


class TestGetAddressPublications:
    async def test_returns_linked_publications(self, async_db):
        await async_db.execute(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi) "
            "VALUES ('T', 't', 2024, 'article', '10.1/a') RETURNING id"
        )
        pub = (await async_db.fetchone())["id"]
        await async_db.execute(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('hal', 'h-1', 'T', %s) RETURNING id",
            (pub,),
        )
        sd = (await async_db.fetchone())["id"]
        await async_db.execute(
            "INSERT INTO source_persons (source, source_id, full_name) VALUES ('hal', 'sp-1', 'X') RETURNING id"
        )
        sp = (await async_db.fetchone())["id"]
        await async_db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id, author_position)
            VALUES ('hal', %s, %s, 0) RETURNING id
            """,
            (sd, sp),
        )
        sa = (await async_db.fetchone())["id"]
        addr = await _create_address(async_db, raw_text="rue X")
        await async_db.execute(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) VALUES (%s, %s)",
            (sa, addr),
        )

        rows = await get_address_publications(async_db, addr, limit=10)
        assert len(rows) == 1
        assert rows[0]["id"] == pub


class TestGetAddressStructures:
    async def test_returns_structures(self, async_db):
        struct = await _create_structure(async_db)
        addr = await _create_address(async_db)
        await _link_addr_struct(async_db, addr, struct, is_confirmed=True)

        rows = await get_address_structures(async_db, addr)
        assert len(rows) == 1
        assert rows[0]["id"] == struct

    async def test_returns_empty_list_when_no_link(self, async_db):
        addr = await _create_address(async_db)
        rows = await get_address_structures(async_db, addr)
        assert rows == []


class TestGetStructureLink:
    async def test_returns_status(self, async_db):
        struct = await _create_structure(async_db)
        addr = await _create_address(async_db)
        await _link_addr_struct(async_db, addr, struct, is_confirmed=True)

        link = await get_structure_link(async_db, addr, struct)
        assert link["is_confirmed"] is True
        assert link["is_detected"] is False

    async def test_returns_none_when_no_link(self, async_db):
        struct = await _create_structure(async_db)
        addr = await _create_address(async_db)
        assert await get_structure_link(async_db, addr, struct) is None


class TestCountryCheckers:
    async def test_list_countries_sorts_xx_first(self, async_db):
        await _ensure_country(async_db, "FR", "France")
        await _ensure_country(async_db, "xx", "Inconnu")

        rows = await list_countries(async_db)
        codes = [r["code"].strip() for r in rows]
        # Tri `(code = 'xx') DESC, name` : TRUE > FALSE → 'xx' arrive en tête
        assert codes[0] == "xx"
        assert "FR" in codes

    async def test_country_exists(self, async_db):
        await _ensure_country(async_db, "FR")
        assert await country_exists(async_db, "FR") is True
        assert await country_exists(async_db, "ZZ") is False

    async def test_address_exists(self, async_db):
        addr = await _create_address(async_db)
        assert await address_exists(async_db, addr) is True
        assert await address_exists(async_db, 999_999) is False


class TestAddressesCountries:
    async def test_returns_addresses_with_countries(self, async_db):
        await _ensure_country(async_db, "FR")
        await _create_address(async_db, raw_text="A", countries=["FR"])
        await _create_address(async_db, raw_text="B", countries=None)

        res = await addresses_countries(
            async_db, filters=AddressCountriesFilters(has_country="yes"), page=1, per_page=50
        )
        assert res["total"] >= 1
        assert all(a["countries"] is not None for a in res["addresses"])

    async def test_filters_by_country_code(self, async_db):
        await _ensure_country(async_db, "FR")
        await _ensure_country(async_db, "US")
        a_fr = await _create_address(async_db, raw_text="A-fr", countries=["FR"])
        await _create_address(async_db, raw_text="A-us", countries=["US"])

        res = await addresses_countries(
            async_db, filters=AddressCountriesFilters(country_code="FR"), page=1, per_page=50
        )
        ids = [a["id"] for a in res["addresses"]]
        assert a_fr in ids
        # La facette countries doit être présente
        assert "country_facets" in res

    async def test_suggest_mode_returns_facets(self, async_db):
        await _ensure_country(async_db, "FR")
        await _create_address(async_db, raw_text="sug", countries=None, suggested_countries=["FR"])
        res = await addresses_countries(
            async_db, filters=AddressCountriesFilters(suggest=True), page=1, per_page=50
        )
        assert "suggestion_facets" in res


class TestSuggestCountries:
    async def test_returns_suggestions_and_without_country(self, async_db):
        await _ensure_country(async_db, "FR")
        await _create_address(async_db, raw_text="With", countries=["FR"])
        await _create_address(async_db, raw_text="Without", countries=None)

        res = await suggest_countries(async_db, search="")
        assert any(s["code"] == "FR" for s in res["suggestions"])
        assert res["without_country"] >= 1

    async def test_filters_by_search(self, async_db):
        await _ensure_country(async_db, "FR")
        await _create_address(async_db, raw_text="Match", countries=["FR"])
        await _create_address(async_db, raw_text="Nope", countries=["FR"])

        res = await suggest_countries(async_db, search="Match")
        assert any(s["code"] == "FR" for s in res["suggestions"])
