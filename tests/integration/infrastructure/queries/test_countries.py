"""Tests d'intégration pour `infrastructure.queries.pipeline.countries`."""

from sqlalchemy import text

from infrastructure.queries.pipeline.countries import (
    refresh_address_source_countries,
    refresh_publication_countries,
    suggest_addresses_countries_batch,
)


def _create_pub(conn, title="X"):
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, doc_type) "
            "VALUES (:title, 2024, 'article') RETURNING id"
        ),
        {"title": title},
    ).scalar_one()


def _create_sd(conn, pub_id, source, source_id, countries=None):
    return conn.execute(
        text("""
            INSERT INTO source_publications (source, source_id, title, publication_id, countries)
            VALUES (:source, :source_id, 'X', :pub_id, :countries) RETURNING id
        """),
        {"source": source, "source_id": source_id, "pub_id": pub_id, "countries": countries},
    ).scalar_one()


def _create_sa(conn, sd_id, source, author_position=0):
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position)
            VALUES (:source, :sd, :pos) RETURNING id
        """),
        {"source": source, "sd": sd_id, "pos": author_position},
    ).scalar_one()


def _create_address(conn, raw_text, countries):
    return conn.execute(
        text(
            "INSERT INTO addresses (raw_text, normalized_text, countries) "
            "VALUES (:raw, :norm, :countries) RETURNING id"
        ),
        {"raw": raw_text, "norm": raw_text, "countries": countries},
    ).scalar_one()


def _ensure_country(conn, code, name="Test"):
    conn.execute(
        text("INSERT INTO countries (code, name) VALUES (:code, :name) ON CONFLICT DO NOTHING"),
        {"code": code, "name": name},
    )


class TestRefreshAddressSourceCountries:
    def test_propagates_country_from_address(self, sa_sync_conn):
        _ensure_country(sa_sync_conn, "FR")
        pub_id = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub_id, "openalex", "oa-1")
        sa = _create_sa(sa_sync_conn, sd, "openalex")
        addr = _create_address(sa_sync_conn, "Clermont", ["FR"])
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
                "VALUES (:sa, :addr)"
            ),
            {"sa": sa, "addr": addr},
        )

        updated = refresh_address_source_countries(sa_sync_conn)
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM source_publications WHERE id = :sd"),
            {"sd": sd},
        ).scalar_one()
        assert result == ["FR"]

    def test_noop_without_address_countries(self, sa_sync_conn):
        pub_id = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub_id, "openalex", "oa-2")
        sa = _create_sa(sa_sync_conn, sd, "openalex")
        addr = _create_address(sa_sync_conn, "X", None)
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
                "VALUES (:sa, :addr)"
            ),
            {"sa": sa, "addr": addr},
        )

        updated = refresh_address_source_countries(sa_sync_conn)
        assert updated == 0


class TestRefreshPublicationCountries:
    def test_unions_all_source_countries(self, sa_sync_conn):
        pub_id = _create_pub(sa_sync_conn)
        _create_sd(sa_sync_conn, pub_id, "hal", "hal-1", countries=["FR"])
        _create_sd(sa_sync_conn, pub_id, "openalex", "oa-1", countries=["US", "FR"])

        updated = refresh_publication_countries(sa_sync_conn)
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM publications WHERE id = :pid"),
            {"pid": pub_id},
        ).scalar_one()
        assert result == ["FR", "US"]

    def test_ignores_source_pubs_without_publication_id(self, sa_sync_conn):
        _create_sd(sa_sync_conn, None, "hal", "hal-orphan", countries=["FR"])
        updated = refresh_publication_countries(sa_sync_conn)
        assert updated == 0

    def test_noop_when_already_up_to_date(self, sa_sync_conn):
        pub_id = _create_pub(sa_sync_conn)
        _create_sd(sa_sync_conn, pub_id, "hal", "hal-1", countries=["FR"])
        sa_sync_conn.execute(
            text("UPDATE publications SET countries = ARRAY['FR'] WHERE id = :pid"),
            {"pid": pub_id},
        )

        updated = refresh_publication_countries(sa_sync_conn)
        assert updated == 0


def _create_address_full_sa(conn, raw_text, normalized_text=None, countries=None, pub_count=0):
    """Helper SA pour `suggest_addresses_countries_batch` (Connection SA)."""
    return conn.execute(
        text("""
            INSERT INTO addresses (raw_text, normalized_text, countries, pub_count)
            VALUES (:raw, :norm, :countries, :pub_count) RETURNING id
        """),
        {
            "raw": raw_text,
            "norm": normalized_text or raw_text.lower(),
            "countries": countries,
            "pub_count": pub_count,
        },
    ).scalar_one()


def _get_address_field_sa(conn, addr_id, field):
    return conn.execute(
        text(f"SELECT {field} FROM addresses WHERE id = :id"),
        {"id": addr_id},
    ).scalar_one()


class TestSuggestAddressesCountriesBatch:
    """Régression : la version bulk SQL doit produire les mêmes suggestions
    que l'ancienne boucle Python (pour chaque cible : pays majoritaire dans
    le pool d'adresses dont normalized_text contient celui de la cible)."""

    def test_picks_majority_country_from_substring_matches(self, sa_sync_conn):
        # Pool : 3 adresses avec FR contenant "lab foo", 1 avec US contenant "lab foo"
        _create_address_full_sa(sa_sync_conn, "Lab Foo, Univ A", "lab foo univ a", countries=["FR"])
        _create_address_full_sa(sa_sync_conn, "Lab Foo, Univ B", "lab foo univ b", countries=["FR"])
        _create_address_full_sa(sa_sync_conn, "Lab Foo, Univ C", "lab foo univ c", countries=["FR"])
        _create_address_full_sa(sa_sync_conn, "Lab Foo, Univ D", "lab foo univ d", countries=["US"])
        target = _create_address_full_sa(sa_sync_conn, "Lab Foo seul", "lab foo")

        n_done, n_found = suggest_addresses_countries_batch(sa_sync_conn, batch_size=10)

        assert n_done == 1
        assert n_found == 1
        assert _get_address_field_sa(sa_sync_conn, target, "suggested_countries") == ["FR"]

    def test_returns_all_tied_countries_sorted(self, sa_sync_conn):
        # Égalité parfaite : 1 FR, 1 US, 1 DE → suggestion = ['DE', 'FR', 'US']
        _create_address_full_sa(sa_sync_conn, "Foo bar A", "foo bar a", countries=["FR"])
        _create_address_full_sa(sa_sync_conn, "Foo bar B", "foo bar b", countries=["US"])
        _create_address_full_sa(sa_sync_conn, "Foo bar C", "foo bar c", countries=["DE"])
        target = _create_address_full_sa(sa_sync_conn, "Foo bar seul", "foo bar")

        suggest_addresses_countries_batch(sa_sync_conn, batch_size=10)

        assert _get_address_field_sa(sa_sync_conn, target, "suggested_countries") == [
            "DE",
            "FR",
            "US",
        ]

    def test_marks_no_match_with_empty_array_to_skip_next_batch(self, sa_sync_conn):
        # Pas de pool → cible reçoit array vide (et non NULL) pour ne pas
        # être retraitée à la passe suivante.
        target = _create_address_full_sa(sa_sync_conn, "Truc inconnu", "truc inconnu")

        n_done, n_found = suggest_addresses_countries_batch(sa_sync_conn, batch_size=10)

        assert n_done == 1
        assert n_found == 0
        assert _get_address_field_sa(sa_sync_conn, target, "suggested_countries") == []

    def test_skips_addresses_already_with_countries(self, sa_sync_conn):
        _create_address_full_sa(sa_sync_conn, "Already done", "already done", countries=["FR"])

        n_done, _ = suggest_addresses_countries_batch(sa_sync_conn, batch_size=10)
        assert n_done == 0

    def test_skips_short_normalized_text(self, sa_sync_conn):
        # length < 5 → exclu de la requête (filtre identique à l'ancienne version)
        _create_address_full_sa(
            sa_sync_conn, "Pool A", "pool", countries=["FR"]
        )  # 4 chars : ignoré
        _create_address_full_sa(sa_sync_conn, "Pool B", "pools", countries=["FR"])  # 5 chars : ok

        n_done, _ = suggest_addresses_countries_batch(sa_sync_conn, batch_size=10)
        assert n_done == 0  # tous sont avec countries

    def test_direct_mode_writes_to_countries(self, sa_sync_conn):
        _create_address_full_sa(sa_sync_conn, "Lab X UCA, FR", "lab x uca fr", countries=["FR"])
        target = _create_address_full_sa(sa_sync_conn, "Lab X UCA", "lab x uca")

        suggest_addresses_countries_batch(sa_sync_conn, batch_size=10, target_column="countries")

        assert _get_address_field_sa(sa_sync_conn, target, "countries") == ["FR"]
        assert _get_address_field_sa(sa_sync_conn, target, "suggested_countries") is None

    def test_invalid_target_column_raises(self, sa_sync_conn):
        import pytest

        with pytest.raises(ValueError):
            suggest_addresses_countries_batch(sa_sync_conn, batch_size=10, target_column="bogus")
