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

    def test_doc_type_family_grouping(self, sa_sync_conn):
        # Le découpage par type se fait au grain « famille » (lisible), pas par type fin.
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}", doc_type="article")  # publications
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}", doc_type="book")  # publications
        _pub(sa_sync_conn, oa_status="closed", sources="{hal}", doc_type="thesis")  # theses

        res = _piv(sa_sync_conn, "pub_count", ["doc_type_family"], doc_types=())
        by_family = {r["doc_type_family"]: r["value"] for r in res["rows"]}
        assert by_family == {"publications": 2, "theses": 1}

    def test_group_by_lab_executes(self, sa_sync_conn):
        # Le groupement par laboratoire compose une requête valide (jointures de rattachement).
        # Smoke test : on vérifie que la requête s'exécute et renvoie la forme attendue, sans
        # dépendre des matviews de rattachement peuplées.
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}")
        res = _piv(sa_sync_conn, "pub_count", ["lab"])
        assert "rows" in res
        assert res["groups"] == ["lab"]

    def test_group_by_publisher_and_journal_execute(self, sa_sync_conn):
        # Éditeur et revue composent des requêtes valides (jointures internes). Smoke test : la
        # requête s'exécute et renvoie la forme attendue, sans dépendre de données peuplées.
        _pub(sa_sync_conn, oa_status="gold", sources="{hal}")
        for dim in ("publisher", "journal"):
            res = _piv(sa_sync_conn, "pub_count", [dim])
            assert res["groups"] == [dim]

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
