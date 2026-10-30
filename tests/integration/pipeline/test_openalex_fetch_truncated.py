"""Moissonnage OpenAlex en masse, et conservation des auteurs complets relus par `fetch_truncated`.

Le moissonnage en masse d'OpenAlex tronque la liste des auteurs à 100. `fetch_truncated` relit ces documents un par un pour obtenir la liste complète. Cette relecture réécrit `raw_data` sans recalculer `raw_hash` : la ligne garde l'empreinte du document tronqué. Tant que le moissonnage suivant renvoie le même document, `raw_data` garde les auteurs complets. Quand le document change, la version tronquée remplace `raw_data`, et `fetch_truncated` la relit dans le même run.
"""

from sqlalchemy import text

from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.common.fingerprint import fingerprint
from pipeline.ingestion.common.harvester import stage_document
from pipeline.ingestion.common.staging import StagingStore
from pipeline.runtime.observability.metrics import PhaseMetrics
from tests.integration.helpers.staging import insert_staging


def insert_batch(conn, works):
    metrics = PhaseMetrics()
    for work in works:
        stage_document(conn, metrics, source="openalex", record=work)
    return metrics


def _make_work(openalex_id, n_authors, title="Test Publication", cited_by_count=10):
    """Construit un document OpenAlex synthétique à `n_authors` auteurs."""
    authorships = [
        {
            "author_position": "first" if i == 0 else "middle",
            "author": {
                "id": f"https://openalex.org/A{i:06d}",
                "display_name": f"Author {i}",
                "orcid": None,
            },
            "institutions": [],
            "raw_author_name": f"Author {i}",
            "raw_affiliation_strings": [],
        }
        for i in range(n_authors)
    ]
    return {
        "id": f"https://openalex.org/{openalex_id}",
        "doi": f"https://doi.org/10.1234/{openalex_id.lower()}",
        "title": title,
        "display_name": title,
        "publication_year": 2024,
        "publication_date": "2024-01-15",
        "type": "article",
        "language": "en",
        "primary_location": {"source": {"display_name": "Test Journal"}},
        "locations": [],
        "open_access": {"is_oa": False, "oa_status": "closed"},
        "authorships": authorships,
        "cited_by_count": cited_by_count,
        "biblio": {"volume": "1", "issue": "1"},
        "is_retracted": False,
    }


def _seed_refetched(conn, *, source_id, full_work, bulk_payload, processed):
    """Insère une ligne de staging relue par `fetch_truncated` : `raw_data` contient la version complète `full_work`, `raw_hash` l'empreinte de la version tronquée `bulk_payload`."""
    insert_staging(
        conn,
        "openalex",
        source_id=source_id,
        doi=full_work["doi"].replace("https://doi.org/", ""),
        raw_data=full_work,
        raw_hash=fingerprint(bulk_payload),
        processed=processed,
    )


def _get_staging(conn, source_id):
    return conn.execute(
        text(
            "SELECT raw_data, raw_hash, processed, authors_truncated FROM staging "
            "WHERE source = 'openalex' AND source_id = :sid"
        ),
        {"sid": source_id},
    ).first()


class TestRawHashUpsert:
    def test_new_row(self, sa_sync_conn):
        """Un document inconnu est inséré avec `raw_data` et `raw_hash`, à normaliser."""
        work = _make_work("W001", 50)
        insert_batch(sa_sync_conn, [work])

        row = _get_staging(sa_sync_conn, "W001")
        assert len(row.raw_data["authorships"]) == 50
        assert row.raw_hash == fingerprint(work)
        assert row.processed is False

    def test_bulk_unchanged_no_op(self, sa_sync_conn):
        """Un document identique laisse la ligne en l'état, `processed` compris."""
        work = _make_work("W002", 50)
        insert_batch(sa_sync_conn, [work])
        sa_sync_conn.execute(
            text("UPDATE staging SET processed=TRUE WHERE source='openalex' AND source_id='W002'")
        )

        counts = insert_batch(sa_sync_conn, [work])

        row = _get_staging(sa_sync_conn, "W002")
        assert row.processed is True
        # Même hash : ni insertion ni réécriture, la ligne compte comme inchangée.
        assert counts.new == 0
        assert counts.updated == 0
        assert counts.unchanged == 1

    def test_bulk_changed_replaces(self, sa_sync_conn):
        """Un document modifié remplace `raw_data` et remet la ligne à normaliser."""
        work = _make_work("W003", 50, title="Original")
        insert_batch(sa_sync_conn, [work])
        sa_sync_conn.execute(
            text("UPDATE staging SET processed=TRUE WHERE source='openalex' AND source_id='W003'")
        )

        new_work = _make_work("W003", 60, title="Updated")
        counts = insert_batch(sa_sync_conn, [new_work])

        row = _get_staging(sa_sync_conn, "W003")
        assert row.raw_data["title"] == "Updated"
        assert len(row.raw_data["authorships"]) == 60
        assert row.processed is False
        assert counts.new == 0 and counts.updated == 1


class TestRefetchPreservation:
    def test_refetched_bulk_unchanged_preserves_full_authors(self, sa_sync_conn):
        """Un document tronqué identique laisse en place les 150 auteurs de la ligne relue."""
        bulk_payload = _make_work("W100", 100, title="Stable")
        full = _make_work("W100", 150, title="Stable")  # mêmes métadonnées, 150 auteurs
        _seed_refetched(
            sa_sync_conn,
            source_id="W100",
            full_work=full,
            bulk_payload=bulk_payload,
            processed=True,
        )

        counts = insert_batch(sa_sync_conn, [bulk_payload])

        row = _get_staging(sa_sync_conn, "W100")
        assert len(row.raw_data["authorships"]) == 150
        assert row.processed is True
        # Même hash : la ligne compte comme inchangée et garde ses 150 auteurs.
        assert counts.new == 0
        assert counts.unchanged == 1

    def test_refetched_bulk_changed_overwrites(self, sa_sync_conn):
        """Un document modifié remplace la version complète de la ligne relue par la version tronquée."""
        bulk_payload_v1 = _make_work("W101", 100, title="Original")
        full = _make_work("W101", 150, title="Original")
        _seed_refetched(
            sa_sync_conn,
            source_id="W101",
            full_work=full,
            bulk_payload=bulk_payload_v1,
            processed=True,
        )

        bulk_payload_v2 = _make_work("W101", 100, title="Updated", cited_by_count=42)
        counts = insert_batch(sa_sync_conn, [bulk_payload_v2])

        row = _get_staging(sa_sync_conn, "W101")
        assert row.raw_data["title"] == "Updated"
        assert row.raw_data["cited_by_count"] == 42
        assert len(row.raw_data["authorships"]) == 100
        # La ligne est à normaliser et marquée tronquée : `fetch_truncated` la relit.
        assert row.processed is False
        assert row.authors_truncated is True
        assert counts.new == 0 and counts.updated == 1


class TestAuthorsTruncatedFlag:
    def test_bulk_100_authors_flags_truncated(self, sa_sync_conn):
        """Un document à 100 auteurs (plafond d'OpenAlex) est marqué tronqué."""
        insert_batch(sa_sync_conn, [_make_work("W200", 100)])
        assert _get_staging(sa_sync_conn, "W200").authors_truncated is True

    def test_fetch_missing_100_authors_flags_truncated(self, sa_sync_conn):
        """La recherche par DOI passe par l'endpoint de liste : un document à 100 auteurs est marqué tronqué, comme au moissonnage."""
        StagingStore(sa_sync_conn).stage(
            "openalex", _make_work("W210", 100), entry_mode=StagingEntryMode.FETCH_MISSING_DOI
        )
        assert _get_staging(sa_sync_conn, "W210").authors_truncated is True

    def test_bulk_under_100_not_flagged(self, sa_sync_conn):
        """Un document sous le plafond est marqué complet."""
        insert_batch(sa_sync_conn, [_make_work("W201", 50)])
        assert _get_staging(sa_sync_conn, "W201").authors_truncated is False

    def test_unchanged_bulk_preserves_cleared_flag(self, sa_sync_conn):
        """Une ligne relue, revue à l'identique, reste marquée complète : `fetch_truncated` la laisse de côté."""
        bulk = _make_work("W202", 100, title="Stable")
        full = _make_work("W202", 150, title="Stable")
        _seed_refetched(
            sa_sync_conn, source_id="W202", full_work=full, bulk_payload=bulk, processed=True
        )
        insert_batch(sa_sync_conn, [bulk])  # même hash : marque inchangée
        assert _get_staging(sa_sync_conn, "W202").authors_truncated is False
