"""Tests d'intégration de l'écriture des localisations et des plateformes (`pipeline.ingestion.common.locations`)."""

from sqlalchemy import text

from domain.platforms.platform import PlatformType
from pipeline.ingestion.common.locations import LocationFacts, LocationStore, PlatformFacts
from tests.integration.helpers.sources import insert_source_record

_HAL = PlatformFacts("S4306402512", "HAL", PlatformType.REPOSITORY)


def _locations(conn, source_record_id: int) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            text(
                "SELECT l.url, l.oai_id, p.name FROM source_record_locations l"
                " LEFT JOIN platforms p ON p.id = l.platform_id"
                " WHERE l.source_record_id = :id ORDER BY l.url"
            ),
            {"id": source_record_id},
        )
    ]


def test_les_localisations_remplacent_les_precedentes(sa_sync_conn):
    source_record = insert_source_record(sa_sync_conn, source="openalex", source_id="W1")
    store = LocationStore(sa_sync_conn)
    store.replace_locations(source_record, [LocationFacts("https://a.org/1")])

    store.replace_locations(
        source_record,
        [
            LocationFacts("https://hal.science/hal-1", oai_id="oai:HAL:hal-1", platform=_HAL),
            LocationFacts("https://doi.org/10.1/x"),
            LocationFacts("https://doi.org/10.1/x", oai_id="doublon"),
        ],
    )

    assert _locations(sa_sync_conn, source_record) == [
        ("https://doi.org/10.1/x", None, None),
        ("https://hal.science/hal-1", "oai:HAL:hal-1", "HAL"),
    ]


def test_la_plateforme_suit_le_nom_et_le_type_de_la_source(sa_sync_conn):
    platform_id = LocationStore(sa_sync_conn).platform_id(_HAL)

    renamed = LocationStore(sa_sync_conn).platform_id(
        PlatformFacts("S4306402512", "HAL Archive ouverte", PlatformType.PREPRINT_SERVER)
    )

    row = sa_sync_conn.execute(
        text("SELECT name, platform_type::text FROM platforms WHERE id = :id"), {"id": platform_id}
    ).one()
    assert renamed == platform_id
    assert tuple(row) == ("HAL Archive ouverte", "preprint_server")


def test_la_suppression_de_l_enregistrement_source_emporte_ses_localisations(sa_sync_conn):
    source_record = insert_source_record(sa_sync_conn, source="openalex", source_id="W2")
    LocationStore(sa_sync_conn).replace_locations(source_record, [LocationFacts("https://a.org/2")])

    sa_sync_conn.execute(text("DELETE FROM source_records WHERE id = :id"), {"id": source_record})

    assert _locations(sa_sync_conn, source_record) == []
