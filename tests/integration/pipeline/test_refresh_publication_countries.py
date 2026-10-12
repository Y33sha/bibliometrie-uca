"""Tests d'intégration pour `pipeline.structures.countries.refresh_publication_countries`.

Recalcul des caches pays depuis `addresses.countries` :
1. `source_publications.countries` — union des pays des adresses des source_authorships du document.
2. `publications.countries` — union des `source_publications.countries` de même publication_id.
"""

from __future__ import annotations

import logging
from functools import partial

import pytest
from sqlalchemy import text

from pipeline.structures.countries.countries_queries import CountryQueries
from pipeline.structures.countries.refresh_publication_countries import refresh
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)

# Notice de 2024, de titre « Test sp », OpenAlex par défaut.
_notice = partial(insert_source_publication, source="openalex", title="Test sp", pub_year=2024)


def _insert_source_authorship(
    conn,
    source_publication_id: int,
    source: str = "openalex",
    raw_author_name: str = "Jane Doe",
    position: int = 0,
) -> int:
    normalized = conn.execute(
        text("SELECT normalize_name_form(:name)"), {"name": raw_author_name}
    ).scalar_one()
    return insert_signature(
        conn,
        source_publication_id,
        source=source,
        author_position=position,
        raw_author_name=raw_author_name,
        author_name_normalized=normalized,
        in_perimeter=True,
    )


def _get_pub_countries(conn, pub_id: int) -> list[str] | None:
    return conn.execute(
        text("SELECT countries FROM publications WHERE id = :id"), {"id": pub_id}
    ).scalar_one()


def _get_sp_countries(conn, sp_id: int) -> list[str] | None:
    return conn.execute(
        text("SELECT countries FROM source_publications WHERE id = :id"), {"id": sp_id}
    ).scalar_one()


@pytest.fixture
def queries() -> CountryQueries:
    return CountryQueries()


@pytest.fixture
def log() -> logging.Logger:
    return logging.getLogger("test_refresh_publication_countries")


class TestCascade:
    def test_single_address_propagates_to_publication(self, sa_sync_conn, queries, log):
        pub = insert_publication(sa_sync_conn)
        sp = _notice(sa_sync_conn, pub, source_id="W1")
        sa = _insert_source_authorship(sa_sync_conn, sp)
        addr = insert_address(sa_sync_conn, "1 rue X, Paris, FR", countries=["fr"])
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        updated = refresh(sa_sync_conn, queries, log)

        assert updated == 1
        assert _get_sp_countries(sa_sync_conn, sp) == ["fr"]
        assert _get_pub_countries(sa_sync_conn, pub) == ["fr"]

    def test_multi_country_union_propagates(self, sa_sync_conn, queries, log):
        # Deux adresses sur le même sa : union des pays remontée jusqu'à pub.
        pub = insert_publication(sa_sync_conn)
        sp = _notice(sa_sync_conn, pub, source_id="W1")
        sa = _insert_source_authorship(sa_sync_conn, sp)
        a1 = insert_address(sa_sync_conn, "addr FR", countries=["fr"])
        a2 = insert_address(sa_sync_conn, "addr US", countries=["us"])
        insert_signature_address(sa_sync_conn, sa, address_id=a1)
        insert_signature_address(sa_sync_conn, sa, address_id=a2)

        refresh(sa_sync_conn, queries, log)

        assert _get_sp_countries(sa_sync_conn, sp) == ["fr", "us"]
        assert _get_pub_countries(sa_sync_conn, pub) == ["fr", "us"]

    def test_multiple_sources_union_at_publication_level(self, sa_sync_conn, queries, log):
        # Même publication via deux sources distinctes (OA et HAL), chacune
        # avec une adresse dans un pays différent → union au niveau publi.
        pub = insert_publication(sa_sync_conn)
        sp_oa = _notice(sa_sync_conn, pub, source_id="W1")
        sp_hal = _notice(sa_sync_conn, pub, source_id="hal-1", source="hal")
        sa_oa = _insert_source_authorship(sa_sync_conn, sp_oa, source="openalex")
        sa_hal = _insert_source_authorship(sa_sync_conn, sp_hal, source="hal", position=1)
        a_fr = insert_address(sa_sync_conn, "addr Paris", countries=["fr"])
        a_de = insert_address(sa_sync_conn, "addr Berlin", countries=["de"])
        insert_signature_address(sa_sync_conn, sa_oa, address_id=a_fr)
        insert_signature_address(sa_sync_conn, sa_hal, address_id=a_de)

        refresh(sa_sync_conn, queries, log)

        assert _get_pub_countries(sa_sync_conn, pub) == ["de", "fr"]

    def test_returns_zero_when_no_changes(self, sa_sync_conn, queries, log):
        # Base sans adresses avec pays → la refresh ne change rien et
        # retourne 0 publications mises à jour.
        pub = insert_publication(sa_sync_conn)
        sp = _notice(sa_sync_conn, pub, source_id="W1")
        _insert_source_authorship(sa_sync_conn, sp)

        updated = refresh(sa_sync_conn, queries, log)

        assert updated == 0
        assert _get_pub_countries(sa_sync_conn, pub) is None


class TestIdempotence:
    def test_double_run_no_extra_update(self, sa_sync_conn, queries, log):
        # Premier run : la publi passe de NULL à ['fr']. Deuxième run :
        # rien à changer, retour 0 (cf. `IS DISTINCT FROM` côté query).
        pub = insert_publication(sa_sync_conn)
        sp = _notice(sa_sync_conn, pub, source_id="W1")
        sa = _insert_source_authorship(sa_sync_conn, sp)
        addr = insert_address(sa_sync_conn, "addr", countries=["fr"])
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        first = refresh(sa_sync_conn, queries, log)
        second = refresh(sa_sync_conn, queries, log)

        assert first == 1
        assert second == 0
        assert _get_pub_countries(sa_sync_conn, pub) == ["fr"]


class TestCleanup:
    def test_resets_source_countries_when_address_lost_country(self, sa_sync_conn, queries, log):
        # source_publications.countries=['fr'] déjà persistées, mais l'adresse du sa
        # n'a plus de `countries` (NULL) → le LEFT JOIN remet sp.countries à NULL.
        pub = insert_publication(sa_sync_conn)
        sp = _notice(sa_sync_conn, pub, source_id="W1")
        sa = _insert_source_authorship(sa_sync_conn, sp)
        sa_sync_conn.execute(
            text("UPDATE source_publications SET countries = ARRAY['fr'] WHERE id = :id"),
            {"id": sp},
        )
        addr = insert_address(sa_sync_conn, "addr no country")
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        refresh(sa_sync_conn, queries, log)

        assert _get_sp_countries(sa_sync_conn, sp) is None
