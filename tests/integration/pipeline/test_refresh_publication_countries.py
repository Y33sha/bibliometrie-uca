"""Tests d'intégration pour `application.pipeline.countries.refresh_publication_countries`.

Cascade complète :
1. `addresses.countries` → `source_authorships.countries` (par source)
2. cleanup des sa polluées (countries non-NULL sans adresses utiles)
3. `source_authorships.countries` → `source_publications.countries`
4. `source_publications.countries` → `publications.countries`
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

from application.pipeline.countries.refresh_publication_countries import refresh
from infrastructure.queries.pipeline.countries import PgCountryQueries


def _insert_publication(conn, title: str = "Test pub", year: int = 2024) -> int:
    return conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES (:t, lower(:t), :y, 'article') RETURNING id"
        ),
        {"t": title, "y": year},
    ).scalar_one()


def _insert_source_publication(
    conn, publication_id: int, source: str = "openalex", source_id: str = "W1"
) -> int:
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, pub_year, publication_id) "
            "VALUES (:src, :sid, 'Test sp', 2024, :pid) RETURNING id"
        ),
        {"src": source, "sid": source_id, "pid": publication_id},
    ).scalar_one()


def _insert_source_authorship(
    conn,
    source_publication_id: int,
    source: str = "openalex",
    raw_author_name: str = "Jane Doe",
    position: int = 0,
    countries: list[str] | None = None,
) -> int:
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, in_perimeter,
                 raw_author_name, author_name_normalized, countries)
            VALUES (:src, :sp, :pos, TRUE, :name, normalize_name_form(:name), :countries)
            RETURNING id
        """),
        {
            "src": source,
            "sp": source_publication_id,
            "pos": position,
            "name": raw_author_name,
            "countries": countries,
        },
    ).scalar_one()


def _insert_address(conn, raw_text: str, countries: list[str] | None) -> int:
    return conn.execute(
        text(
            "INSERT INTO addresses (raw_text, normalized_text, countries) "
            "VALUES (:r, lower(:r), :c) RETURNING id"
        ),
        {"r": raw_text, "c": countries},
    ).scalar_one()


def _link_sa_address(conn, sa_id: int, address_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
            "VALUES (:s, :a)"
        ),
        {"s": sa_id, "a": address_id},
    )


def _get_pub_countries(conn, pub_id: int) -> list[str] | None:
    return conn.execute(
        text("SELECT countries FROM publications WHERE id = :id"), {"id": pub_id}
    ).scalar_one()


def _get_sp_countries(conn, sp_id: int) -> list[str] | None:
    return conn.execute(
        text("SELECT countries FROM source_publications WHERE id = :id"), {"id": sp_id}
    ).scalar_one()


def _get_sa_countries(conn, sa_id: int) -> list[str] | None:
    return conn.execute(
        text("SELECT countries FROM source_authorships WHERE id = :id"), {"id": sa_id}
    ).scalar_one()


@pytest.fixture
def queries() -> PgCountryQueries:
    return PgCountryQueries()


@pytest.fixture
def log() -> logging.Logger:
    return logging.getLogger("test_refresh_publication_countries")


class TestCascade:
    def test_single_address_propagates_to_publication(self, sa_sync_conn, queries, log):
        pub = _insert_publication(sa_sync_conn)
        sp = _insert_source_publication(sa_sync_conn, pub)
        sa = _insert_source_authorship(sa_sync_conn, sp)
        addr = _insert_address(sa_sync_conn, "1 rue X, Paris, FR", countries=["fr"])
        _link_sa_address(sa_sync_conn, sa, addr)

        updated = refresh(sa_sync_conn, queries, log)

        assert updated == 1
        assert _get_sa_countries(sa_sync_conn, sa) == ["fr"]
        assert _get_sp_countries(sa_sync_conn, sp) == ["fr"]
        assert _get_pub_countries(sa_sync_conn, pub) == ["fr"]

    def test_multi_country_union_propagates(self, sa_sync_conn, queries, log):
        # Deux adresses sur le même sa : union des pays remontée jusqu'à pub.
        pub = _insert_publication(sa_sync_conn)
        sp = _insert_source_publication(sa_sync_conn, pub)
        sa = _insert_source_authorship(sa_sync_conn, sp)
        a1 = _insert_address(sa_sync_conn, "addr FR", countries=["fr"])
        a2 = _insert_address(sa_sync_conn, "addr US", countries=["us"])
        _link_sa_address(sa_sync_conn, sa, a1)
        _link_sa_address(sa_sync_conn, sa, a2)

        refresh(sa_sync_conn, queries, log)

        assert _get_sa_countries(sa_sync_conn, sa) == ["fr", "us"]
        assert _get_pub_countries(sa_sync_conn, pub) == ["fr", "us"]

    def test_multiple_sources_union_at_publication_level(self, sa_sync_conn, queries, log):
        # Même publication via deux sources distinctes (OA et HAL), chacune
        # avec une adresse dans un pays différent → union au niveau publi.
        pub = _insert_publication(sa_sync_conn)
        sp_oa = _insert_source_publication(sa_sync_conn, pub, source="openalex", source_id="W1")
        sp_hal = _insert_source_publication(sa_sync_conn, pub, source="hal", source_id="hal-1")
        sa_oa = _insert_source_authorship(sa_sync_conn, sp_oa, source="openalex")
        sa_hal = _insert_source_authorship(sa_sync_conn, sp_hal, source="hal", position=1)
        a_fr = _insert_address(sa_sync_conn, "addr Paris", countries=["fr"])
        a_de = _insert_address(sa_sync_conn, "addr Berlin", countries=["de"])
        _link_sa_address(sa_sync_conn, sa_oa, a_fr)
        _link_sa_address(sa_sync_conn, sa_hal, a_de)

        refresh(sa_sync_conn, queries, log)

        assert _get_pub_countries(sa_sync_conn, pub) == ["de", "fr"]

    def test_returns_zero_when_no_changes(self, sa_sync_conn, queries, log):
        # Base sans adresses avec pays → la refresh ne change rien et
        # retourne 0 publications mises à jour.
        pub = _insert_publication(sa_sync_conn)
        sp = _insert_source_publication(sa_sync_conn, pub)
        _insert_source_authorship(sa_sync_conn, sp)

        updated = refresh(sa_sync_conn, queries, log)

        assert updated == 0
        assert _get_pub_countries(sa_sync_conn, pub) is None


class TestIdempotence:
    def test_double_run_no_extra_update(self, sa_sync_conn, queries, log):
        # Premier run : la publi passe de NULL à ['fr']. Deuxième run :
        # rien à changer, retour 0 (cf. `IS DISTINCT FROM` côté query).
        pub = _insert_publication(sa_sync_conn)
        sp = _insert_source_publication(sa_sync_conn, pub)
        sa = _insert_source_authorship(sa_sync_conn, sp)
        addr = _insert_address(sa_sync_conn, "addr", countries=["fr"])
        _link_sa_address(sa_sync_conn, sa, addr)

        first = refresh(sa_sync_conn, queries, log)
        second = refresh(sa_sync_conn, queries, log)

        assert first == 1
        assert second == 0
        assert _get_pub_countries(sa_sync_conn, pub) == ["fr"]


class TestCleanup:
    def test_resets_sa_countries_when_address_lost_country(self, sa_sync_conn, queries, log):
        # sa avec `countries=['fr']` déjà persistées (par exemple par un
        # ancien run), mais maintenant son adresse n'a plus `countries`
        # (NULL) → la pass cleanup remet sa.countries à NULL.
        pub = _insert_publication(sa_sync_conn)
        sp = _insert_source_publication(sa_sync_conn, pub)
        sa = _insert_source_authorship(sa_sync_conn, sp, countries=["fr"])
        addr = _insert_address(sa_sync_conn, "addr no country", countries=None)
        _link_sa_address(sa_sync_conn, sa, addr)

        refresh(sa_sync_conn, queries, log)

        assert _get_sa_countries(sa_sync_conn, sa) is None

    def test_resets_sa_countries_when_no_address(self, sa_sync_conn, queries, log):
        # sa avec `countries=['fr']` mais aucune saa du tout (cas pathologique
        # mais possible si une saa a été supprimée manuellement) → reset.
        pub = _insert_publication(sa_sync_conn)
        sp = _insert_source_publication(sa_sync_conn, pub)
        sa = _insert_source_authorship(sa_sync_conn, sp, countries=["fr"])

        refresh(sa_sync_conn, queries, log)

        assert _get_sa_countries(sa_sync_conn, sa) is None
