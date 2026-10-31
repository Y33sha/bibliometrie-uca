"""La normalisation écrit la licence de l'enregistrement source dans la colonne `license_type`."""

from sqlalchemy import text

from domain.publications.dates import PublicationDate
from domain.publications.licenses import License
from pipeline.ingestion.common.source_records import (
    SourceRecordStore,
    SourceRecordUpsert,
)
from tests.integration.helpers.staging import insert_staging


def test_licence_ecrite_puis_reecrite(sa_sync_conn):
    staging_id = insert_staging(sa_sync_conn, "openalex", source_id="W_license")

    def upsert(found: License | None) -> str | None:
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            SourceRecordUpsert(
                source="openalex",
                source_id="W_license",
                staging_id=staging_id,
                title="Titre",
                publication_date=PublicationDate.of_year(2024),
                license=found,
            ),
        )
        return sa_sync_conn.execute(
            text("SELECT license::text FROM source_records WHERE id = :id"),
            {"id": source_record_id},
        ).scalar_one()

    assert upsert(License.CC_BY_NC_ND) == "cc-by-nc-nd"
    assert upsert(None) is None
