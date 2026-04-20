"""Tests d'intégration pour `infrastructure.db.queries.addresses`."""

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


def _create_structure(db, code="UCA"):
    db.execute(
        "INSERT INTO structures (code, name, structure_type) VALUES (%s, 'X', 'universite') RETURNING id",
        (code,),
    )
    return db.fetchone()["id"]


def _create_address(db, raw_text="X", countries=None, pub_count=0, suggested_countries=None):
    db.execute(
        """
        INSERT INTO addresses (raw_text, normalized_text, countries, pub_count, suggested_countries)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (raw_text, raw_text.lower(), countries, pub_count, suggested_countries),
    )
    return db.fetchone()["id"]


def _link_addr_struct(db, addr_id, struct_id, *, is_confirmed=None, matched_form_id=None):
    db.execute(
        """
        INSERT INTO address_structures (address_id, structure_id, is_confirmed, matched_form_id)
        VALUES (%s, %s, %s, %s)
        """,
        (addr_id, struct_id, is_confirmed, matched_form_id),
    )


def _ensure_country(db, code, name="Test"):
    db.execute(
        "INSERT INTO countries (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (code, name),
    )


class TestResolveDefaultStructureId:
    def test_returns_first_root_from_perimeter(self, db):
        s1 = _create_structure(db, code="UCA-1")
        s2 = _create_structure(db, code="UCA-2")
        db.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', %s)",
            ([s1, s2],),
        )
        db.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', to_jsonb('uca'::text))"
        )

        resolved = resolve_default_structure_id(db)
        assert resolved == s1

    def test_returns_zero_when_no_perimeter(self, db):
        assert resolve_default_structure_id(db) == 0


class TestListAddresses:
    def test_lists_detected_and_pending_by_default(self, db):
        struct = _create_structure(db)
        # Form pour matched_form_id
        db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'x') RETURNING id",
            (struct,),
        )
        form_id = db.fetchone()["id"]

        addr_pending = _create_address(db, raw_text="a-pending")
        _link_addr_struct(db, addr_pending, struct, matched_form_id=form_id)  # détectée, pending

        addr_confirmed = _create_address(db, raw_text="a-confirmed")
        _link_addr_struct(db, addr_confirmed, struct, matched_form_id=form_id, is_confirmed=True)

        res = list_addresses(
            db, structure_id=struct, filters=AddressListFilters(), page=1, per_page=10
        )
        ids = [a["id"] for a in res["addresses"]]
        assert addr_pending in ids
        assert addr_confirmed not in ids  # validation=pending → exclut confirmed

    def test_lists_confirmed_only(self, db):
        struct = _create_structure(db)
        db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'x') RETURNING id",
            (struct,),
        )
        form_id = db.fetchone()["id"]
        addr = _create_address(db, raw_text="A")
        _link_addr_struct(db, addr, struct, matched_form_id=form_id, is_confirmed=True)

        res = list_addresses(
            db,
            structure_id=struct,
            filters=AddressListFilters(validation="confirmed"),
            page=1,
            per_page=10,
        )
        assert any(a["id"] == addr for a in res["addresses"])

    def test_search_filter(self, db):
        struct = _create_structure(db)
        db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'x') RETURNING id",
            (struct,),
        )
        form_id = db.fetchone()["id"]
        a1 = _create_address(db, raw_text="Université Clermont")
        a2 = _create_address(db, raw_text="Université Paris")
        _link_addr_struct(db, a1, struct, matched_form_id=form_id)
        _link_addr_struct(db, a2, struct, matched_form_id=form_id)

        res = list_addresses(
            db,
            structure_id=struct,
            filters=AddressListFilters(search="Clermont"),
            page=1,
            per_page=10,
        )
        ids = [a["id"] for a in res["addresses"]]
        assert a1 in ids
        assert a2 not in ids


class TestGetAddressBasic:
    def test_returns_none_for_missing(self, db):
        assert get_address_basic(db, 999_999) is None

    def test_returns_address(self, db):
        addr = _create_address(db, raw_text="rue X")
        row = get_address_basic(db, addr)
        assert row["id"] == addr
        assert row["raw_text"] == "rue X"


class TestGetAddressPublications:
    def test_returns_linked_publications(self, db):
        db.execute(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi) "
            "VALUES ('T', 't', 2024, 'article', '10.1/a') RETURNING id"
        )
        pub = db.fetchone()["id"]
        db.execute(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('hal', 'h-1', 'T', %s) RETURNING id",
            (pub,),
        )
        sd = db.fetchone()["id"]
        db.execute(
            "INSERT INTO source_persons (source, source_id, full_name) VALUES ('hal', 'sp-1', 'X') RETURNING id"
        )
        sp = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id, author_position)
            VALUES ('hal', %s, %s, 0) RETURNING id
            """,
            (sd, sp),
        )
        sa = db.fetchone()["id"]
        addr = _create_address(db, raw_text="rue X")
        db.execute(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) VALUES (%s, %s)",
            (sa, addr),
        )

        rows = get_address_publications(db, addr, limit=10)
        assert len(rows) == 1
        assert rows[0]["id"] == pub


class TestGetAddressStructures:
    def test_returns_structures(self, db):
        struct = _create_structure(db)
        addr = _create_address(db)
        _link_addr_struct(db, addr, struct, is_confirmed=True)

        rows = get_address_structures(db, addr)
        assert len(rows) == 1
        assert rows[0]["id"] == struct

    def test_returns_empty_list_when_no_link(self, db):
        addr = _create_address(db)
        rows = get_address_structures(db, addr)
        assert rows == []


class TestGetStructureLink:
    def test_returns_status(self, db):
        struct = _create_structure(db)
        addr = _create_address(db)
        _link_addr_struct(db, addr, struct, is_confirmed=True)

        link = get_structure_link(db, addr, struct)
        assert link["is_confirmed"] is True
        assert link["is_detected"] is False

    def test_returns_none_when_no_link(self, db):
        struct = _create_structure(db)
        addr = _create_address(db)
        assert get_structure_link(db, addr, struct) is None


class TestCountryCheckers:
    def test_list_countries_sorts_xx_first(self, db):
        _ensure_country(db, "FR", "France")
        _ensure_country(db, "xx", "Inconnu")

        rows = list_countries(db)
        codes = [r["code"].strip() for r in rows]
        # Tri `(code = 'xx') DESC, name` : TRUE > FALSE → 'xx' arrive en tête
        assert codes[0] == "xx"
        assert "FR" in codes

    def test_country_exists(self, db):
        _ensure_country(db, "FR")
        assert country_exists(db, "FR") is True
        assert country_exists(db, "ZZ") is False

    def test_address_exists(self, db):
        addr = _create_address(db)
        assert address_exists(db, addr) is True
        assert address_exists(db, 999_999) is False


class TestAddressesCountries:
    def test_returns_addresses_with_countries(self, db):
        _ensure_country(db, "FR")
        _create_address(db, raw_text="A", countries=["FR"])
        _create_address(db, raw_text="B", countries=None)

        res = addresses_countries(
            db, filters=AddressCountriesFilters(has_country="yes"), page=1, per_page=50
        )
        assert res["total"] >= 1
        assert all(a["countries"] is not None for a in res["addresses"])

    def test_filters_by_country_code(self, db):
        _ensure_country(db, "FR")
        _ensure_country(db, "US")
        a_fr = _create_address(db, raw_text="A-fr", countries=["FR"])
        _create_address(db, raw_text="A-us", countries=["US"])

        res = addresses_countries(
            db, filters=AddressCountriesFilters(country_code="FR"), page=1, per_page=50
        )
        ids = [a["id"] for a in res["addresses"]]
        assert a_fr in ids
        # La facette countries doit être présente
        assert "country_facets" in res

    def test_suggest_mode_returns_facets(self, db):
        _ensure_country(db, "FR")
        _create_address(db, raw_text="sug", countries=None, suggested_countries=["FR"])
        res = addresses_countries(
            db, filters=AddressCountriesFilters(suggest=True), page=1, per_page=50
        )
        assert "suggestion_facets" in res


class TestSuggestCountries:
    def test_returns_suggestions_and_without_country(self, db):
        _ensure_country(db, "FR")
        _create_address(db, raw_text="With", countries=["FR"])
        _create_address(db, raw_text="Without", countries=None)

        res = suggest_countries(db, search="")
        assert any(s["code"] == "FR" for s in res["suggestions"])
        assert res["without_country"] >= 1

    def test_filters_by_search(self, db):
        _ensure_country(db, "FR")
        _create_address(db, raw_text="Match", countries=["FR"])
        _create_address(db, raw_text="Nope", countries=["FR"])

        res = suggest_countries(db, search="Match")
        assert any(s["code"] == "FR" for s in res["suggestions"])
