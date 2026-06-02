"""Tests d'intégration — UPSERT bulk OpenAlex + préservation des authorships
refetchées via raw_hash.

OpenAlex bulk tronque à 100 auteurs. `refetch_truncated` re-télécharge
ces publications individuellement pour obtenir la liste complète. Le
mécanisme de préservation lors des bulks ultérieurs repose sur une
dissymétrie volontaire : **refetch ne recalcule pas `raw_hash`**, donc
la ligne refetchée garde le hash du payload bulk. Tant que le bulk
renvoie le même payload, l'UPSERT ne touche pas `raw_data` (qui contient
pourtant les auteurs complets). Quand le bulk renvoie un payload
différent, l'UPSERT écrase `raw_data` avec la version tronquée et le
refetch suivant (dans le même run pipeline) ré-amorce le cycle.
"""

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.sources.common import compute_hash
from infrastructure.sources.openalex.extract_openalex import PgOpenalexExtractAdapter

_adapter = PgOpenalexExtractAdapter(base_url="https://api.openalex.org/works")


def insert_batch(conn, works):
    return _adapter.insert_batch(conn, works)


def _make_work(openalex_id, n_authors, title="Test Publication", cited_by_count=10):
    """Crée un work OpenAlex synthétique avec n auteurs."""
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


_SEED_REFETCHED_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES ('openalex', :source_id, :doi, :raw_data, :raw_hash, :processed)
    """
).bindparams(bindparam("raw_data", type_=JSONB))


def _seed_refetched(conn, *, source_id, full_work, bulk_payload, processed):
    """Pose une ligne staging dans l'état post-refetch.

    `full_work` est la version complète (>100 auteurs) qui a été
    persistée par le refetch. `bulk_payload` est la version tronquée
    initiale dont le hash est conservé en base (c'est l'invariant
    de préservation : refetch ne recalcule pas `raw_hash`).
    """
    conn.execute(
        _SEED_REFETCHED_SQL,
        {
            "source_id": source_id,
            "doi": full_work["doi"].replace("https://doi.org/", ""),
            "raw_data": full_work,
            "raw_hash": compute_hash(bulk_payload),
            "processed": processed,
        },
    )


def _get_staging(conn, source_id):
    return conn.execute(
        text(
            "SELECT raw_data, raw_hash, processed FROM staging "
            "WHERE source = 'openalex' AND source_id = :sid"
        ),
        {"sid": source_id},
    ).first()


class TestRawHashUpsert:
    def test_new_row(self, sa_sync_conn):
        """Insert nouveau via bulk → raw_data + raw_hash posés, processed=FALSE."""
        work = _make_work("W001", 50)
        insert_batch(sa_sync_conn, [work])

        row = _get_staging(sa_sync_conn, "W001")
        assert len(row.raw_data["authorships"]) == 50
        assert row.raw_hash == compute_hash(work)
        assert row.processed is False

    def test_bulk_unchanged_no_op(self, sa_sync_conn):
        """Bulk identique → raw_data inchangé, processed préservé."""
        work = _make_work("W002", 50)
        insert_batch(sa_sync_conn, [work])
        sa_sync_conn.execute(
            text("UPDATE staging SET processed=TRUE WHERE source='openalex' AND source_id='W002'")
        )

        counts = insert_batch(sa_sync_conn, [work])

        row = _get_staging(sa_sync_conn, "W002")
        assert row.processed is True
        # Hash identique → ni insertion ni réécriture : compté `unchanged`.
        assert counts.new == 0
        assert counts.updated == 0
        assert counts.unchanged == 1

    def test_bulk_changed_replaces(self, sa_sync_conn):
        """Bulk modifié → raw_data remplacé, processed=FALSE."""
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
        """Bulk identique sur ligne refetchée → 150 auteurs en base, inchangés."""
        bulk_payload = _make_work("W100", 100, title="Stable")
        full = _make_work("W100", 150, title="Stable")  # mêmes métadonnées, plus d'auteurs
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
        # Hash identique → no-op : compté `unchanged`, raw_data (150 auteurs) préservé.
        assert counts.new == 0
        assert counts.unchanged == 1

    def test_refetched_bulk_changed_overwrites(self, sa_sync_conn):
        """Bulk modifié sur ligne refetchée → écrasement par la version tronquée
        (le refetch suivant dans le même run pipeline ré-amorcera le cycle).
        """
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
        # raw_data écrasé par la version tronquée v2
        assert row.raw_data["title"] == "Updated"
        assert row.raw_data["cited_by_count"] == 42
        assert len(row.raw_data["authorships"]) == 100
        # processed remis à FALSE → normalize re-passera, et refetch dans
        # le même run pipeline re-pickera (count=100, processed=FALSE)
        assert row.processed is False
        assert counts.new == 0 and counts.updated == 1
