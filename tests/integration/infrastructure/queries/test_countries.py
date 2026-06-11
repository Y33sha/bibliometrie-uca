"""Tests d'intégration pour `infrastructure.queries.pipeline.countries`."""

from sqlalchemy import text

from infrastructure.queries.pipeline.countries import (
    count_suggest_eligible,
    fetch_suggest_targets_chunk,
    load_country_pool,
    refresh_address_source_countries,
    refresh_publication_countries,
    write_suggested_countries,
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


class TestSuggestCountryQueries:
    """Requêtes de la passe suggest : sélection des cibles (keyset + éligibilité +
    recompute_all), chargement du pool, écriture bulk idempotente. Le matching
    (cible → pays) est couvert en unit par `CountrySuggester`."""

    def test_fetch_targets_excludes_ineligible(self, sa_sync_conn):
        eligible = _create_address_full_sa(sa_sync_conn, "Lab Foo seul", "lab foo seul")
        countried = _create_address_full_sa(sa_sync_conn, "Done", "already done", countries=["FR"])
        short = _create_address_full_sa(sa_sync_conn, "Sh", "abcd")  # 4 chars
        suggested = _create_address_full_sa(sa_sync_conn, "Sug", "sug done")
        write_suggested_countries(sa_sync_conn, [(suggested, ["FR"])])

        ids = {i for i, _ in fetch_suggest_targets_chunk(sa_sync_conn, after_id=0, limit=1000)}
        assert eligible in ids
        assert countried not in ids  # a déjà des pays
        assert short not in ids  # normalized_text < 5
        assert suggested not in ids  # déjà tentée

    def test_fetch_targets_keyset_after_id(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab aaa seul")
        b = _create_address_full_sa(sa_sync_conn, "B", "lab bbb seul")
        ids = {i for i, _ in fetch_suggest_targets_chunk(sa_sync_conn, after_id=a, limit=1000)}
        assert a not in ids and b in ids

    def test_fetch_recompute_all_includes_already_attempted(self, sa_sync_conn):
        fresh = _create_address_full_sa(sa_sync_conn, "Fresh", "lab fresh seul")
        attempted = _create_address_full_sa(sa_sync_conn, "Att", "lab attempted seul")
        write_suggested_countries(sa_sync_conn, [(attempted, ["FR"])])  # déjà tentée
        inc = {i for i, _ in fetch_suggest_targets_chunk(sa_sync_conn, after_id=0, limit=1000)}
        assert fresh in inc and attempted not in inc  # incrémental : exclut la déjà-tentée
        full = {
            i
            for i, _ in fetch_suggest_targets_chunk(
                sa_sync_conn, after_id=0, limit=1000, recompute_all=True
            )
        }
        assert fresh in full and attempted in full  # recompute_all : inclut la déjà-tentée

    def test_load_pool_returns_only_countried(self, sa_sync_conn):
        _create_address_full_sa(sa_sync_conn, "P", "lab pool a", countries=["FR"])
        _create_address_full_sa(sa_sync_conn, "N", "lab no country")
        texts = {t for t, _ in load_country_pool(sa_sync_conn)}
        assert "lab pool a" in texts
        assert "lab no country" not in texts

    def test_write_suggested_array_and_empty(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab a seul")
        b = _create_address_full_sa(sa_sync_conn, "B", "lab b seul")
        write_suggested_countries(sa_sync_conn, [(a, ["FR"]), (b, [])])
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["FR"]
        # array vide (et non NULL) : marque « tentée sans match » pour la sauter ensuite.
        assert _get_address_field_sa(sa_sync_conn, b, "suggested_countries") == []

    def test_write_direct_to_countries(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab a seul")
        write_suggested_countries(sa_sync_conn, [(a, ["FR"])], target_column="countries")
        assert _get_address_field_sa(sa_sync_conn, a, "countries") == ["FR"]
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") is None

    def test_write_invalid_column_raises(self, sa_sync_conn):
        import pytest

        with pytest.raises(ValueError):
            write_suggested_countries(sa_sync_conn, [(1, ["FR"])], target_column="bogus")

    def test_write_idempotent_same_value_then_overwrite(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab a seul")
        write_suggested_countries(sa_sync_conn, [(a, ["FR"])])
        write_suggested_countries(sa_sync_conn, [(a, ["FR"])])  # même valeur : no-op
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["FR"]
        write_suggested_countries(sa_sync_conn, [(a, ["BE"])])  # valeur différente : écrase
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["BE"]

    def test_count_eligible(self, sa_sync_conn):
        _create_address_full_sa(sa_sync_conn, "E", "lab eligible seul")
        attempted = _create_address_full_sa(sa_sync_conn, "A", "lab attempted seul")
        write_suggested_countries(sa_sync_conn, [(attempted, [])])  # tentée sans match
        counts = count_suggest_eligible(sa_sync_conn)
        assert counts.eligible >= 1  # la fraîche (suggested_countries IS NULL)
        assert counts.all_eligible > counts.eligible  # all_eligible inclut aussi la tentée
