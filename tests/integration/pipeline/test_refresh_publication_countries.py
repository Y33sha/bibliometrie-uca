"""Recalcul des pays depuis `addresses.countries` (`pipeline.transformation.countries.refresh_publication_countries`) :

1. `source_records.countries` : union des pays des adresses des contributions sources de l'enregistrement source.
2. `publications.countries` : union des pays des enregistrements sources de la publication.
"""

from __future__ import annotations

import logging
from functools import partial

import pytest
from sqlalchemy import text

from domain.normalize import normalize_text
from pipeline.transformation.countries.refresh_publication_countries import refresh
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)

# Enregistrement source de 2024, de titre « Test sp », OpenAlex par défaut.
_source_record = partial(
    insert_source_record, source="openalex", title="Test sp", publication_year=2024
)


def _insert_source_contribution(
    conn,
    source_record_id: int,
    source: str = "openalex",
    raw_author_name: str = "Jane Doe",
    position: int = 0,
) -> int:
    normalized = normalize_text(raw_author_name)
    return insert_source_contribution(
        conn,
        source_record_id,
        source=source,
        author_position=position,
        raw_author_name=raw_author_name,
        author_name_normalized=normalized,
        in_perimeter=True,
    )


def _get_publication_countries(conn, publication_id: int) -> list[str] | None:
    return conn.execute(
        text("SELECT countries FROM publications WHERE id = :id"), {"id": publication_id}
    ).scalar_one()


def _get_source_record_countries(conn, source_record_id: int) -> list[str] | None:
    return conn.execute(
        text("SELECT countries FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()


@pytest.fixture
def log() -> logging.Logger:
    return logging.getLogger("test_refresh_publication_countries")


class TestCascade:
    def test_single_address_propagates_to_publication(self, sa_sync_conn, log):
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source_id="W1")
        sa = _insert_source_contribution(sa_sync_conn, source_record)
        addr = insert_address(sa_sync_conn, "1 rue X, Paris, FR", countries=["fr"])
        insert_source_contribution_address(sa_sync_conn, sa, address_id=addr)

        updated = refresh(sa_sync_conn, log)

        assert updated == 1
        assert _get_source_record_countries(sa_sync_conn, source_record) == ["fr"]
        assert _get_publication_countries(sa_sync_conn, publication) == ["fr"]

    def test_multi_country_union_propagates(self, sa_sync_conn, log):
        # Deux adresses pour la même contribution source : la publication reçoit l'union des pays.
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source_id="W1")
        sa = _insert_source_contribution(sa_sync_conn, source_record)
        a1 = insert_address(sa_sync_conn, "addr FR", countries=["fr"])
        a2 = insert_address(sa_sync_conn, "addr US", countries=["us"])
        insert_source_contribution_address(sa_sync_conn, sa, address_id=a1)
        insert_source_contribution_address(sa_sync_conn, sa, address_id=a2)

        refresh(sa_sync_conn, log)

        assert _get_source_record_countries(sa_sync_conn, source_record) == ["fr", "us"]
        assert _get_publication_countries(sa_sync_conn, publication) == ["fr", "us"]

    def test_multiple_sources_union_at_publication_level(self, sa_sync_conn, log):
        # Deux enregistrements sources (OpenAlex et HAL) de la même publication, avec des adresses de pays différents : la publication reçoit l'union des pays.
        publication = insert_publication(sa_sync_conn)
        source_record_oa = _source_record(sa_sync_conn, publication, source_id="W1")
        source_record_hal = _source_record(
            sa_sync_conn, publication, source_id="hal-1", source="hal"
        )
        source_contribution_oa = _insert_source_contribution(
            sa_sync_conn, source_record_oa, source="openalex"
        )
        source_contribution_hal = _insert_source_contribution(
            sa_sync_conn, source_record_hal, source="hal", position=1
        )
        a_fr = insert_address(sa_sync_conn, "addr Paris", countries=["fr"])
        a_de = insert_address(sa_sync_conn, "addr Berlin", countries=["de"])
        insert_source_contribution_address(sa_sync_conn, source_contribution_oa, address_id=a_fr)
        insert_source_contribution_address(sa_sync_conn, source_contribution_hal, address_id=a_de)

        refresh(sa_sync_conn, log)

        assert _get_publication_countries(sa_sync_conn, publication) == ["de", "fr"]

    def test_returns_zero_when_no_changes(self, sa_sync_conn, log):
        # Sans adresse avec pays, le recalcul laisse la publication en l'état : zéro mise à jour.
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source_id="W1")
        _insert_source_contribution(sa_sync_conn, source_record)

        updated = refresh(sa_sync_conn, log)

        assert updated == 0
        assert _get_publication_countries(sa_sync_conn, publication) is None


class TestIdempotence:
    def test_double_run_no_extra_update(self, sa_sync_conn, log):
        # Le premier passage donne ['fr'] à la publication. Le second trouve les pays à jour et compte zéro mise à jour.
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source_id="W1")
        sa = _insert_source_contribution(sa_sync_conn, source_record)
        addr = insert_address(sa_sync_conn, "addr", countries=["fr"])
        insert_source_contribution_address(sa_sync_conn, sa, address_id=addr)

        first = refresh(sa_sync_conn, log)
        second = refresh(sa_sync_conn, log)

        assert first == 1
        assert second == 0
        assert _get_publication_countries(sa_sync_conn, publication) == ["fr"]


class TestCleanup:
    def test_resets_source_countries_when_address_lost_country(self, sa_sync_conn, log):
        # L'enregistrement source a ['fr'], mais l'adresse de sa contribution source est sans pays : ses pays reviennent à NULL.
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source_id="W1")
        sa = _insert_source_contribution(sa_sync_conn, source_record)
        sa_sync_conn.execute(
            text("UPDATE source_records SET countries = ARRAY['fr'] WHERE id = :id"),
            {"id": source_record},
        )
        addr = insert_address(sa_sync_conn, "addr no country")
        insert_source_contribution_address(sa_sync_conn, sa, address_id=addr)

        refresh(sa_sync_conn, log)

        assert _get_source_record_countries(sa_sync_conn, source_record) is None
