"""Tests d'intégration pour `pipeline.transformation.structures.countries.countries_queries`."""

from sqlalchemy import text

from pipeline.transformation.structures.countries.countries_queries import CountryQueries
from tests.integration.helpers.addresses import ensure_country, insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)

_Q = CountryQueries()


class TestRefreshAddressSourceCountries:
    def test_propagates_country_from_address(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "FR")
        pub_id = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub_id, source="openalex", source_id="oa-1")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")
        addr = insert_address(
            sa_sync_conn, "Clermont", countries=["FR"], normalized_text="Clermont"
        )
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        updated = _Q.refresh_address_source_countries(sa_sync_conn)
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM source_publications WHERE id = :sd"),
            {"sd": sd},
        ).scalar_one()
        assert result == ["FR"]

    def test_noop_without_address_countries(self, sa_sync_conn):
        pub_id = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub_id, source="openalex", source_id="oa-2")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")
        addr = insert_address(sa_sync_conn, "X", countries=None, normalized_text="X")
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        updated = _Q.refresh_address_source_countries(sa_sync_conn)
        assert updated == 0


class TestRefreshPublicationCountries:
    def test_unions_all_source_countries(self, sa_sync_conn):
        pub_id = insert_publication(sa_sync_conn)
        sd1 = insert_source_publication(
            sa_sync_conn, pub_id, source="hal", source_id="hal-1", countries=["FR"]
        )
        sd2 = insert_source_publication(
            sa_sync_conn, pub_id, source="openalex", source_id="oa-1", countries=["US", "FR"]
        )
        # un sa (dirty par défaut) met la publication dans la portée du refresh.
        insert_signature(sa_sync_conn, sd1, source="hal")
        insert_signature(sa_sync_conn, sd2, source="openalex")

        updated = _Q.refresh_publication_countries(sa_sync_conn)
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM publications WHERE id = :pid"),
            {"pid": pub_id},
        ).scalar_one()
        assert result == ["FR", "US"]

    def test_ignores_source_pubs_without_publication_id(self, sa_sync_conn):
        insert_source_publication(
            sa_sync_conn, None, source="hal", source_id="hal-orphan", countries=["FR"]
        )
        updated = _Q.refresh_publication_countries(sa_sync_conn)
        assert updated == 0

    def test_noop_when_already_up_to_date(self, sa_sync_conn):
        pub_id = insert_publication(sa_sync_conn)
        sd = insert_source_publication(
            sa_sync_conn, pub_id, source="hal", source_id="hal-1", countries=["FR"]
        )
        insert_signature(sa_sync_conn, sd, source="hal")  # dirty → publication dans la portée
        sa_sync_conn.execute(
            text("UPDATE publications SET countries = ARRAY['FR'] WHERE id = :pid"),
            {"pid": pub_id},
        )

        updated = _Q.refresh_publication_countries(sa_sync_conn)
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


class TestDirtyDrivenSourceCountries:
    """Refresh `source_publications.countries` borné aux documents dont un source_authorship
    est dirty : `source_authorships.countries_dirty` (nouveaux sa) OU lié à une adresse
    `countries_dirty` (pays changé). + orphelin (LEFT JOIN), flag adresse, clear."""

    def test_only_dirty_sources_recomputed(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        dirty_sd = insert_source_publication(
            sa_sync_conn, pub, source="openalex", source_id="oa-dirty"
        )
        clean_sd = insert_source_publication(sa_sync_conn, pub, source="hal", source_id="hal-clean")
        dirty_sa = insert_signature(sa_sync_conn, dirty_sd, source="openalex")  # dirty par défaut
        clean_sa = insert_signature(sa_sync_conn, clean_sd, source="hal")
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE id = :i"),
            {"i": clean_sa},
        )
        insert_signature_address(
            sa_sync_conn,
            dirty_sa,
            address_id=insert_address(
                sa_sync_conn, "Lyon", countries=["FR"], normalized_text="Lyon"
            ),
        )
        insert_signature_address(
            sa_sync_conn,
            clean_sa,
            address_id=insert_address(
                sa_sync_conn, "Boston", countries=["US"], normalized_text="Boston"
            ),
        )

        _Q.refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, dirty_sd) == ["FR"]
        assert _sp_countries(sa_sync_conn, clean_sd) is None  # aucun sa dirty → pas recalculé

    def test_orphan_dirty_source_reset_to_null(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(
            sa_sync_conn, pub, source="openalex", source_id="oa-o", countries=["FR"]
        )
        sa = insert_signature(sa_sync_conn, sd, source="openalex")  # dirty, adresse sans pays
        insert_signature_address(
            sa_sync_conn,
            sa,
            address_id=insert_address(sa_sync_conn, "X", countries=None, normalized_text="X"),
        )

        _Q.refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, sd) is None  # orphelin → NULL

    def test_dirty_address_drives_source_recompute(self, sa_sync_conn):
        # Un document NON dirty est recalculé parce que l'adresse de son sa devient dirty.
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub, source="openalex", source_id="oa-m")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE id = :i"), {"i": sa}
        )
        addr = insert_address(sa_sync_conn, "Nantes", countries=None, normalized_text="Nantes")
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        # write_countries(countries) pose addresses.countries_dirty sur la ligne changée.
        _Q.write_countries(sa_sync_conn, [(addr, ["FR"])], target_column="countries")
        assert _addr_dirty(sa_sync_conn, addr) is True
        _Q.refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, sd) == ["FR"]  # recalculé via l'adresse dirty

    def test_clear_dirty_clears_both_flags(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub, source="openalex", source_id="oa-c")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")  # sa dirty par défaut
        addr = insert_address(sa_sync_conn, "Paris", countries=None, normalized_text="Paris")
        _Q.write_countries(sa_sync_conn, [(addr, ["FR"])], target_column="countries")  # addr dirty
        _Q.clear_countries_dirty(sa_sync_conn)
        assert _sa_dirty(sa_sync_conn, sa) is False
        assert _addr_dirty(sa_sync_conn, addr) is False


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
        eligible = insert_address(sa_sync_conn, "Lab Foo seul", normalized_text="lab foo seul")
        countried = insert_address(
            sa_sync_conn, "Done", normalized_text="already done", countries=["FR"]
        )
        short = insert_address(sa_sync_conn, "Sh", normalized_text="lyon")
        suggested = insert_address(sa_sync_conn, "Sug", normalized_text="sug done")
        _Q.write_countries(sa_sync_conn, [(suggested, ["FR"])])

        ids = {i for i, _ in _Q.fetch_suggest_targets_chunk(sa_sync_conn, after_id=0, limit=1000)}
        assert eligible in ids
        assert short in ids  # la longueur du texte ne conditionne pas l'éligibilité
        assert countried not in ids  # a déjà des pays
        assert suggested not in ids  # déjà tentée

    def test_fetch_targets_keyset_after_id(self, sa_sync_conn):
        a = insert_address(sa_sync_conn, "A", normalized_text="lab aaa seul")
        b = insert_address(sa_sync_conn, "B", normalized_text="lab bbb seul")
        ids = {i for i, _ in _Q.fetch_suggest_targets_chunk(sa_sync_conn, after_id=a, limit=1000)}
        assert a not in ids and b in ids

    def test_fetch_retry_empty_includes_empties_not_positives(self, sa_sync_conn):
        fresh = insert_address(sa_sync_conn, "Fresh", normalized_text="lab fresh seul")
        empty = insert_address(sa_sync_conn, "Empty", normalized_text="lab empty seul")
        positive = insert_address(sa_sync_conn, "Pos", normalized_text="lab positive seul")
        _Q.write_countries(sa_sync_conn, [(empty, []), (positive, ["FR"])])
        inc = {i for i, _ in _Q.fetch_suggest_targets_chunk(sa_sync_conn, after_id=0, limit=1000)}
        assert fresh in inc and empty not in inc and positive not in inc  # incrémental : nouvelles
        full = {
            i
            for i, _ in _Q.fetch_suggest_targets_chunk(
                sa_sync_conn, after_id=0, limit=1000, retry_empty=True
            )
        }
        # retry_empty : nouvelles + vides, mais pas les positives.
        assert fresh in full and empty in full and positive not in full

    def test_load_pool_returns_only_countried(self, sa_sync_conn):
        insert_address(sa_sync_conn, "P", normalized_text="lab pool a", countries=["FR"])
        insert_address(sa_sync_conn, "N", normalized_text="lab no country")
        texts = {t for t, _ in _Q.load_country_pool(sa_sync_conn)}
        assert "lab pool a" in texts
        assert "lab no country" not in texts

    def test_write_suggested_array_and_empty(self, sa_sync_conn):
        a = insert_address(sa_sync_conn, "A", normalized_text="lab a seul")
        b = insert_address(sa_sync_conn, "B", normalized_text="lab b seul")
        _Q.write_countries(sa_sync_conn, [(a, ["FR"]), (b, [])])
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["FR"]
        # array vide (et non NULL) : marque « tentée sans match » pour la sauter ensuite.
        assert _get_address_field_sa(sa_sync_conn, b, "suggested_countries") == []

    def test_write_direct_to_countries(self, sa_sync_conn):
        a = insert_address(sa_sync_conn, "A", normalized_text="lab a seul")
        _Q.write_countries(sa_sync_conn, [(a, ["FR"])], target_column="countries")
        assert _get_address_field_sa(sa_sync_conn, a, "countries") == ["FR"]
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") is None

    def test_write_invalid_column_raises(self, sa_sync_conn):
        import pytest

        with pytest.raises(ValueError):
            _Q.write_countries(sa_sync_conn, [(1, ["FR"])], target_column="bogus")

    def test_write_idempotent_same_value_then_overwrite(self, sa_sync_conn):
        a = insert_address(sa_sync_conn, "A", normalized_text="lab a seul")
        _Q.write_countries(sa_sync_conn, [(a, ["FR"])])
        _Q.write_countries(sa_sync_conn, [(a, ["FR"])])  # même valeur : no-op
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["FR"]
        _Q.write_countries(sa_sync_conn, [(a, ["BE"])])  # valeur différente : écrase
        assert _get_address_field_sa(sa_sync_conn, a, "suggested_countries") == ["BE"]

    def test_count_eligible(self, sa_sync_conn):
        insert_address(sa_sync_conn, "E", normalized_text="lab eligible seul")
        attempted = insert_address(sa_sync_conn, "A", normalized_text="lab attempted seul")
        _Q.write_countries(sa_sync_conn, [(attempted, [])])  # tentée sans match
        counts = _Q.count_suggest_eligible(sa_sync_conn)
        assert counts.eligible >= 1  # la fraîche (suggested_countries IS NULL)
        assert counts.empty_attempted >= 1  # la tentée sans match (`= []`)
