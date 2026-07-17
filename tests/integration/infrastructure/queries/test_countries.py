"""Tests d'intégration pour `infrastructure.queries.pipeline.countries`."""

from sqlalchemy import text

from infrastructure.queries.pipeline.countries import (
    clear_countries_dirty,
    count_suggest_eligible,
    fetch_suggest_targets_chunk,
    load_country_pool,
    refresh_address_source_countries,
    refresh_publication_countries,
    write_countries,
)
from tests.integration.helpers.authorships import upsert_identity


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
    identity_id = upsert_identity(conn)
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, identity_id)
            VALUES (:source, :sd, :pos, :iid) RETURNING id
        """),
        {"source": source, "sd": sd_id, "pos": author_position, "iid": identity_id},
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
        sd1 = _create_sd(sa_sync_conn, pub_id, "hal", "hal-1", countries=["FR"])
        sd2 = _create_sd(sa_sync_conn, pub_id, "openalex", "oa-1", countries=["US", "FR"])
        # un sa (dirty par défaut) met la publication dans la portée du refresh.
        _create_sa(sa_sync_conn, sd1, "hal")
        _create_sa(sa_sync_conn, sd2, "openalex")

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
        sd = _create_sd(sa_sync_conn, pub_id, "hal", "hal-1", countries=["FR"])
        _create_sa(sa_sync_conn, sd, "hal")  # dirty → publication dans la portée
        sa_sync_conn.execute(
            text("UPDATE publications SET countries = ARRAY['FR'] WHERE id = :pid"),
            {"pid": pub_id},
        )

        updated = refresh_publication_countries(sa_sync_conn)
        assert updated == 0


def _sp_countries(conn, sp_id):
    return conn.execute(
        text("SELECT countries FROM source_publications WHERE id = :i"), {"i": sp_id}
    ).scalar_one()


def _sa_dirty(conn, sa_id):
    return conn.execute(
        text("SELECT countries_dirty FROM source_authorships WHERE id = :i"), {"i": sa_id}
    ).scalar_one()


def _addr_dirty(conn, addr_id):
    return conn.execute(
        text("SELECT countries_dirty FROM addresses WHERE id = :i"), {"i": addr_id}
    ).scalar_one()


def _link_sa_address(conn, sa_id, addr_id):
    conn.execute(
        text(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
            "VALUES (:s, :a)"
        ),
        {"s": sa_id, "a": addr_id},
    )


class TestDirtyDrivenSourceCountries:
    """Refresh `source_publications.countries` borné aux documents dont un source_authorship
    est dirty : `source_authorships.countries_dirty` (nouveaux sa) OU lié à une adresse
    `countries_dirty` (pays changé). + orphelin (LEFT JOIN), flag adresse, clear."""

    def test_only_dirty_sources_recomputed(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        dirty_sd = _create_sd(sa_sync_conn, pub, "openalex", "oa-dirty")
        clean_sd = _create_sd(sa_sync_conn, pub, "hal", "hal-clean")
        dirty_sa = _create_sa(sa_sync_conn, dirty_sd, "openalex")  # dirty par défaut
        clean_sa = _create_sa(sa_sync_conn, clean_sd, "hal")
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE id = :i"),
            {"i": clean_sa},
        )
        _link_sa_address(sa_sync_conn, dirty_sa, _create_address(sa_sync_conn, "Lyon", ["FR"]))
        _link_sa_address(sa_sync_conn, clean_sa, _create_address(sa_sync_conn, "Boston", ["US"]))

        refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, dirty_sd) == ["FR"]
        assert _sp_countries(sa_sync_conn, clean_sd) is None  # aucun sa dirty → pas recalculé

    def test_orphan_dirty_source_reset_to_null(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub, "openalex", "oa-o", countries=["FR"])
        sa = _create_sa(sa_sync_conn, sd, "openalex")  # dirty, adresse sans pays
        _link_sa_address(sa_sync_conn, sa, _create_address(sa_sync_conn, "X", None))

        refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, sd) is None  # orphelin → NULL

    def test_dirty_address_drives_source_recompute(self, sa_sync_conn):
        # Un document NON dirty est recalculé parce que l'adresse de son sa devient dirty.
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub, "openalex", "oa-m")
        sa = _create_sa(sa_sync_conn, sd, "openalex")
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE id = :i"), {"i": sa}
        )
        addr = _create_address(sa_sync_conn, "Nantes", None)
        _link_sa_address(sa_sync_conn, sa, addr)

        # write_countries(countries) pose addresses.countries_dirty sur la ligne changée.
        write_countries(sa_sync_conn, [(addr, ["FR"])], target_column="countries")
        assert _addr_dirty(sa_sync_conn, addr) is True
        refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, sd) == ["FR"]  # recalculé via l'adresse dirty

    def test_clear_dirty_clears_both_flags(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub, "openalex", "oa-c")
        sa = _create_sa(sa_sync_conn, sd, "openalex")  # sa dirty par défaut
        addr = _create_address(sa_sync_conn, "Paris", None)
        write_countries(sa_sync_conn, [(addr, ["FR"])], target_column="countries")  # addr dirty
        clear_countries_dirty(sa_sync_conn)
        assert _sa_dirty(sa_sync_conn, sa) is False
        assert _addr_dirty(sa_sync_conn, addr) is False


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
    retry_empty), chargement du pool, écriture bulk idempotente. Le matching
    (cible → pays) est couvert en unit par `CountrySuggester`."""

    def test_fetch_targets_excludes_ineligible(self, sa_sync_conn):
        eligible = _create_address_full_sa(sa_sync_conn, "Lab Foo seul", "lab foo seul")
        countried = _create_address_full_sa(sa_sync_conn, "Done", "already done", countries=["FR"])
        short = _create_address_full_sa(sa_sync_conn, "Sh", "lyon")
        suggested = _create_address_full_sa(sa_sync_conn, "Sug", "sug done")
        write_countries(sa_sync_conn, [(suggested, ["FR"])])

        ids = {i for i, _ in fetch_suggest_targets_chunk(sa_sync_conn, after_id=0, limit=1000)}
        assert eligible in ids
        assert short in ids  # la longueur du texte ne conditionne pas l'éligibilité
        assert countried not in ids  # a déjà des pays
        assert suggested not in ids  # déjà tentée

    def test_fetch_targets_keyset_after_id(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab aaa seul")
        b = _create_address_full_sa(sa_sync_conn, "B", "lab bbb seul")
        ids = {i for i, _ in fetch_suggest_targets_chunk(sa_sync_conn, after_id=a, limit=1000)}
        assert a not in ids and b in ids

    def test_fetch_retry_empty_includes_empties_not_positives(self, sa_sync_conn):
        fresh = _create_address_full_sa(sa_sync_conn, "Fresh", "lab fresh seul")
        empty = _create_address_full_sa(sa_sync_conn, "Empty", "lab empty seul")
        positive = _create_address_full_sa(sa_sync_conn, "Pos", "lab positive seul")
        write_countries(sa_sync_conn, [(empty, []), (positive, ["FR"])])
        inc = {i for i, _ in fetch_suggest_targets_chunk(sa_sync_conn, after_id=0, limit=1000)}
        assert fresh in inc and empty not in inc and positive not in inc  # incrémental : nouvelles
        full = {
            i
            for i, _ in fetch_suggest_targets_chunk(
                sa_sync_conn, after_id=0, limit=1000, retry_empty=True
            )
        }
        # retry_empty : nouvelles + vides, mais pas les positives.
        assert fresh in full and empty in full and positive not in full

    def test_load_pool_returns_only_countried(self, sa_sync_conn):
        _create_address_full_sa(sa_sync_conn, "P", "lab pool a", countries=["FR"])
        _create_address_full_sa(sa_sync_conn, "N", "lab no country")
        texts = {t for t, _ in load_country_pool(sa_sync_conn)}
        assert "lab pool a" in texts
        assert "lab no country" not in texts

    def test_write_suggested_array_and_empty(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab a seul")
        b = _create_address_full_sa(sa_sync_conn, "B", "lab b seul")
        write_countries(sa_sync_conn, [(a, ["FR"]), (b, [])])
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["FR"]
        # array vide (et non NULL) : marque « tentée sans match » pour la sauter ensuite.
        assert _get_address_field_sa(sa_sync_conn, b, "suggested_countries") == []

    def test_write_direct_to_countries(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab a seul")
        write_countries(sa_sync_conn, [(a, ["FR"])], target_column="countries")
        assert _get_address_field_sa(sa_sync_conn, a, "countries") == ["FR"]
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") is None

    def test_write_invalid_column_raises(self, sa_sync_conn):
        import pytest

        with pytest.raises(ValueError):
            write_countries(sa_sync_conn, [(1, ["FR"])], target_column="bogus")

    def test_write_idempotent_same_value_then_overwrite(self, sa_sync_conn):
        a = _create_address_full_sa(sa_sync_conn, "A", "lab a seul")
        write_countries(sa_sync_conn, [(a, ["FR"])])
        write_countries(sa_sync_conn, [(a, ["FR"])])  # même valeur : no-op
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["FR"]
        write_countries(sa_sync_conn, [(a, ["BE"])])  # valeur différente : écrase
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["BE"]

    def test_count_eligible(self, sa_sync_conn):
        _create_address_full_sa(sa_sync_conn, "E", "lab eligible seul")
        attempted = _create_address_full_sa(sa_sync_conn, "A", "lab attempted seul")
        write_countries(sa_sync_conn, [(attempted, [])])  # tentée sans match
        counts = count_suggest_eligible(sa_sync_conn)
        assert counts.eligible >= 1  # la fraîche (suggested_countries IS NULL)
        assert counts.empty_attempted >= 1  # la tentée sans match (`= []`)
