"""Recherche dans theses.fr de la phase `fetch_missing` : sélection des NNT (`pipeline.ingestion.theses.fetch_missing`)."""

from pipeline.ingestion.theses.fetch_missing import get_missing_nnts
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers
from tests.integration.helpers.staging import insert_failed_lookup, insert_staging


def _carry(conn, source, source_id, nnt):
    """Enregistrement source `source` qui contient le NNT `nnt`, avec sa ligne de staging."""
    staging_id = insert_staging(conn, source, source_id=source_id)
    insert_source_record(
        conn,
        insert_publication(conn),
        source=source,
        source_id=source_id,
        staging_id=staging_id,
        identifiers=secondary_identifiers({"nnt": nnt}),
    )


def _missing(conn) -> list[str]:
    return get_missing_nnts(conn, retry_after_days=30)


def test_nnt_d_une_autre_source_absent_de_theses(sa_sync_conn):
    _carry(sa_sync_conn, "scanr", "nnt2019aixm0001", "2019AIXM0001")
    assert "2019AIXM0001" in _missing(sa_sync_conn)


def test_nnt_deja_dans_le_staging_theses_ecarte(sa_sync_conn):
    _carry(sa_sync_conn, "scanr", "nnt2019aixm0002", "2019AIXM0002")
    insert_staging(sa_sync_conn, "theses", source_id="2019AIXM0002")
    assert "2019AIXM0002" not in _missing(sa_sync_conn)


def test_nnt_absent_de_theses_fr_ecarte_apres_le_delai(sa_sync_conn):
    """theses.fr attribue les NNT : l'échec de la recherche est définitif."""
    _carry(sa_sync_conn, "scanr", "nnt2019aixm0004", "2019AIXM0004")
    insert_failed_lookup(
        sa_sync_conn, "theses", id_type="nnt", id_value="2019AIXM0004", not_found_days_ago=60
    )
    assert "2019AIXM0004" not in _missing(sa_sync_conn)
