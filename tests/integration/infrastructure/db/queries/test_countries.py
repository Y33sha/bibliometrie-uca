"""Tests d'intégration pour `infrastructure.db.queries.countries`."""

from infrastructure.db.queries.countries import (
    refresh_address_source_countries,
    refresh_hal_source_countries,
    refresh_publication_countries,
)


def _create_pub(db, title="X"):
    db.execute(
        "INSERT INTO publications (title, pub_year, doc_type) VALUES (%s, 2024, 'article') RETURNING id",
        (title,),
    )
    return db.fetchone()["id"]


def _create_sd(db, pub_id, source, source_id, countries=None):
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, publication_id, countries)
        VALUES (%s, %s, 'X', %s, %s) RETURNING id
        """,
        (source, source_id, pub_id, countries),
    )
    return db.fetchone()["id"]


def _create_sp(db, source="hal", source_id="sp-1"):
    db.execute(
        "INSERT INTO source_persons (source, source_id, full_name) VALUES (%s, %s, 'X') RETURNING id",
        (source, source_id),
    )
    return db.fetchone()["id"]


def _create_source_structure(db, source, source_id, country):
    db.execute(
        """
        INSERT INTO source_structures (source, source_id, name, country)
        VALUES (%s, %s, 'Lab', %s) RETURNING id
        """,
        (source, source_id, country),
    )
    return db.fetchone()["id"]


def _create_sa(db, sd_id, sp_id, source, source_struct_ids=None):
    db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position, source_struct_ids)
        VALUES (%s, %s, %s, 0, %s) RETURNING id
        """,
        (source, sd_id, sp_id, source_struct_ids),
    )
    return db.fetchone()["id"]


def _create_address(db, raw_text, countries):
    db.execute(
        "INSERT INTO addresses (raw_text, normalized_text, countries) VALUES (%s, %s, %s) RETURNING id",
        (raw_text, raw_text, countries),
    )
    return db.fetchone()["id"]


def _ensure_country(db, code, name="Test"):
    db.execute(
        "INSERT INTO countries (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (code, name),
    )


class TestRefreshHalSourceCountries:
    def test_propagates_country_from_struct(self, db):
        pub_id = _create_pub(db)
        sd = _create_sd(db, pub_id, "hal", "hal-1")
        sp = _create_sp(db)
        ss = _create_source_structure(db, "hal", "s1", "FR")
        _create_sa(db, sd, sp, "hal", source_struct_ids=[ss])

        updated = refresh_hal_source_countries(db)
        assert updated == 1

        db.execute("SELECT countries FROM source_publications WHERE id = %s", (sd,))
        assert db.fetchone()["countries"] == ["FR"]

    def test_noop_when_already_up_to_date(self, db):
        pub_id = _create_pub(db)
        sd = _create_sd(db, pub_id, "hal", "hal-2", countries=["FR"])
        sp = _create_sp(db, source_id="sp-2")
        ss = _create_source_structure(db, "hal", "s2", "FR")
        _create_sa(db, sd, sp, "hal", source_struct_ids=[ss])

        updated = refresh_hal_source_countries(db)
        assert updated == 0

    def test_ignores_non_hal_sources(self, db):
        pub_id = _create_pub(db)
        sd = _create_sd(db, pub_id, "openalex", "oa-1")
        sp = _create_sp(db, source="openalex", source_id="oa-p1")
        ss = _create_source_structure(db, "openalex", "oa-s1", "FR")
        _create_sa(db, sd, sp, "openalex", source_struct_ids=[ss])

        updated = refresh_hal_source_countries(db)
        assert updated == 0


class TestRefreshAddressSourceCountries:
    def test_propagates_country_from_address(self, db):
        _ensure_country(db, "FR")
        pub_id = _create_pub(db)
        sd = _create_sd(db, pub_id, "openalex", "oa-1")
        sp = _create_sp(db, source="openalex", source_id="oa-p1")
        sa = _create_sa(db, sd, sp, "openalex")
        addr = _create_address(db, "Clermont", ["FR"])
        db.execute(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) VALUES (%s, %s)",
            (sa, addr),
        )

        updated = refresh_address_source_countries(db)
        assert updated == 1

        db.execute("SELECT countries FROM source_publications WHERE id = %s", (sd,))
        assert db.fetchone()["countries"] == ["FR"]

    def test_noop_without_address_countries(self, db):
        pub_id = _create_pub(db)
        sd = _create_sd(db, pub_id, "openalex", "oa-2")
        sp = _create_sp(db, source="openalex", source_id="oa-p2")
        sa = _create_sa(db, sd, sp, "openalex")
        addr = _create_address(db, "X", None)
        db.execute(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) VALUES (%s, %s)",
            (sa, addr),
        )

        updated = refresh_address_source_countries(db)
        assert updated == 0


class TestRefreshPublicationCountries:
    def test_unions_all_source_countries(self, db):
        pub_id = _create_pub(db)
        _create_sd(db, pub_id, "hal", "hal-1", countries=["FR"])
        _create_sd(db, pub_id, "openalex", "oa-1", countries=["US", "FR"])

        updated = refresh_publication_countries(db)
        assert updated == 1

        db.execute("SELECT countries FROM publications WHERE id = %s", (pub_id,))
        assert db.fetchone()["countries"] == ["FR", "US"]

    def test_ignores_source_pubs_without_publication_id(self, db):
        _create_sd(db, None, "hal", "hal-orphan", countries=["FR"])
        updated = refresh_publication_countries(db)
        assert updated == 0

    def test_noop_when_already_up_to_date(self, db):
        pub_id = _create_pub(db)
        _create_sd(db, pub_id, "hal", "hal-1", countries=["FR"])
        db.execute("UPDATE publications SET countries = ARRAY['FR'] WHERE id = %s", (pub_id,))

        updated = refresh_publication_countries(db)
        assert updated == 0
