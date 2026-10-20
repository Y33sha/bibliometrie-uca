"""Intégration : l'upsert de la normalisation écrit la licence de la notice dans la colonne `license_type`."""

from sqlalchemy import text

from domain.publications.licenses import License
from pipeline.ingestion.common.source_records import (
    SourceRecordQueries,
    SourceRecordUpsert,
)
from tests.integration.helpers.staging import insert_staging

_Q = SourceRecordQueries()


def test_licence_ecrite_puis_reecrite(sa_sync_conn):
    staging_id = insert_staging(sa_sync_conn, "openalex", source_id="W_license")

    def upsert(found: License | None) -> str | None:
        sp_id = _Q.upsert_source_record(
            sa_sync_conn,
            SourceRecordUpsert(
                source="openalex",
                source_id="W_license",
                staging_id=staging_id,
                title="Titre",
                publication_year=2024,
                license=found,
            ),
        )
        return sa_sync_conn.execute(
            text("SELECT license::text FROM source_records WHERE id = :id"), {"id": sp_id}
        ).scalar_one()

    assert upsert(License.CC_BY_NC_ND) == "cc-by-nc-nd"
    assert upsert(None) is None
