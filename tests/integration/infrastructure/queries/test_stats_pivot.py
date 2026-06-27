"""Tests d'intégration du moteur de pivot (`infrastructure.queries.api.stats.pivot`)."""

from sqlalchemy import text

from infrastructure.queries.api.stats.pivot import run_pivot


def _pub(conn, *, oa_status, sources, year=2024, doc_type="article"):
    return conn.execute(
        text("""
            INSERT INTO publications
                (title, title_normalized, pub_year, doc_type, oa_status, sources, in_perimeter)
            VALUES ('X', 'x', :y, CAST(:dt AS doc_type), CAST(:oa AS oa_type),
                    CAST(:src AS source_type[]), TRUE)
            RETURNING id
        """),
        {"y": year, "dt": doc_type, "oa": oa_status, "src": sources},
    ).scalar_one()


def _piv(conn, measure, groups, doc_types=("article", "review")):
    return run_pivot(
        conn,
        measure=measure,
        groups=list(groups),
        apc_structure_ids=[],
        lab_ids=[],
        years=[],
        publisher_id=None,
        journal_id=None,
        oa_status="",
        has_apc="",
        doc_types=list(doc_types),
    )


class TestPivotEngine:
    def test_oa_access_buckets(self, sa_sync_conn):
        _pub(sa_sync_conn, oa_status="gold", sources="{hal,openalex}")
        _pub(sa_sync_conn, oa_status="closed", sources="{hal}")
        _pub(sa_sync_conn, oa_status="gold", sources="{openalex}", year=2023)

        res = _piv(sa_sync_conn, "pub_count", ["oa_access"])
        by_access = {r["oa_access"]: r["value"] for r in res["rows"]}
        assert by_access == {"ouvert": 2, "ferme": 1}

    def test_pct_open_ratio(self, sa_sync_conn):
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}", year=2024)
        _pub(sa_sync_conn, oa_status="closed", sources="{hal}", year=2024)
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}", year=2023)

        res = _piv(sa_sync_conn, "pct_open", ["year"])
        by_year = {r["year"]: float(r["value"]) for r in res["rows"]}
        assert by_year == {2024: 50.0, 2023: 100.0}

    def test_zero_groups_returns_single_total(self, sa_sync_conn):
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}")
        _pub(sa_sync_conn, oa_status="closed", sources="{hal}")

        res = _piv(sa_sync_conn, "pub_count", [])
        assert res["rows"] == [{"value": 2}]

    def test_doc_type_is_a_filter_not_hardcoded(self, sa_sync_conn):
        # Un type hors article/review est exclu par le filtre, pas par le périmètre du moteur.
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}", doc_type="article")
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}", doc_type="book")

        restricted = _piv(sa_sync_conn, "pub_count", [], doc_types=("article", "review"))
        assert restricted["rows"] == [{"value": 1}]
        unrestricted = _piv(sa_sync_conn, "pub_count", [], doc_types=())
        assert unrestricted["rows"] == [{"value": 2}]
