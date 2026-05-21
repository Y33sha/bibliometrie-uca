"""Tests de caractérisation pour le router admin pipeline_runs.

Couvre :
- /api/admin/pipeline-runs : liste vide + liste ordonnée par ran_at desc, champs résumés
- /api/admin/pipeline-runs/{id} : payload complet + 404 sur id inconnu
"""

import json
import os
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.rows import dict_row

_DB_ARGS = {
    "dbname": "bibliometrie_test",
    "user": os.environ["DB_USER"],
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "5432")),
}
if os.environ.get("DB_PASSWORD"):
    _DB_ARGS["password"] = os.environ["DB_PASSWORD"]


@contextmanager
def _conn():
    c = psycopg.connect(**_DB_ARGS, row_factory=dict_row)
    c.autocommit = True
    try:
        with c.cursor() as cur:
            yield cur
    finally:
        c.close()


def _sample_payload(*, sources: list[str], phases: list[str], duration: float) -> dict:
    """Payload minimal mais complet (TypedDict RunSnapshotPayload)."""
    return {
        "observables": {
            "volumes": {"publications": 100},
            "orphans": {"publications_no_authorships": 0},
            "distributions": {"doc_type": {"article": 1.0}},
            "matching_quality": {"ambiguous_name_forms": 0},
        },
        "metrics_per_phase": {
            "extract": {
                "new": 50,
                "updated": 10,
                "total": 60,
                "errors": 0,
                "extras": {},
                "duration_s": 12.3,
            },
        },
        "total_duration_s": duration,
        "sources": sources,
        "phases_run": phases,
    }


@pytest.fixture
def _clean_table():
    """Nettoie pipeline_run_snapshots avant et après le test."""
    with _conn() as cur:
        cur.execute("DELETE FROM pipeline_run_snapshots")
    yield
    with _conn() as cur:
        cur.execute("DELETE FROM pipeline_run_snapshots")


class TestListPipelineRuns:
    def test_empty_returns_empty_list(self, _clean_table, auth_client):
        r = auth_client.get("/api/admin/pipeline-runs")
        assert r.status_code == 200
        assert r.json() == []

    def test_lists_recent_first(self, _clean_table, auth_client):
        with _conn() as cur:
            cur.execute(
                "INSERT INTO pipeline_run_snapshots (ran_at, mode, payload) "
                "VALUES (now() - interval '1 hour', 'full', %s::jsonb)",
                (json.dumps(_sample_payload(sources=["hal"], phases=["extract"], duration=100.0)),),
            )
            cur.execute(
                "INSERT INTO pipeline_run_snapshots (ran_at, mode, payload) "
                "VALUES (now(), 'weekly', %s::jsonb)",
                (
                    json.dumps(
                        _sample_payload(
                            sources=["hal", "openalex"],
                            phases=["extract", "normalize"],
                            duration=200.0,
                        )
                    ),
                ),
            )

        r = auth_client.get("/api/admin/pipeline-runs")
        assert r.status_code == 200
        runs = r.json()
        assert len(runs) == 2
        # Plus récent en premier
        assert runs[0]["mode"] == "weekly"
        assert runs[0]["sources"] == ["hal", "openalex"]
        assert runs[0]["phases_run"] == ["extract", "normalize"]
        assert runs[0]["total_duration_s"] == 200.0
        assert runs[1]["mode"] == "full"

    def test_limit_parameter(self, _clean_table, auth_client):
        with _conn() as cur:
            for _ in range(5):
                cur.execute(
                    "INSERT INTO pipeline_run_snapshots (mode, payload) VALUES ('full', %s::jsonb)",
                    (json.dumps(_sample_payload(sources=[], phases=[], duration=0.0)),),
                )
        r = auth_client.get("/api/admin/pipeline-runs?limit=3")
        assert r.status_code == 200
        assert len(r.json()) == 3


class TestGetPipelineRun:
    def test_returns_full_payload(self, _clean_table, auth_client):
        payload = _sample_payload(sources=["hal"], phases=["extract"], duration=42.0)
        with _conn() as cur:
            cur.execute(
                "INSERT INTO pipeline_run_snapshots (mode, payload) "
                "VALUES ('full', %s::jsonb) RETURNING id",
                (json.dumps(payload),),
            )
            run_id = cur.fetchone()["id"]

        r = auth_client.get(f"/api/admin/pipeline-runs/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == run_id
        assert body["mode"] == "full"
        assert body["payload"]["observables"]["volumes"]["publications"] == 100
        assert body["payload"]["metrics_per_phase"]["extract"]["new"] == 50
        assert body["payload"]["total_duration_s"] == 42.0
        # Premier snapshot pour ce mode → pas de précédent, pas d'observations suspectes
        assert body["previous_snapshot_at"] is None
        assert all(o["suspect"] is False for o in body["observations"])

    def test_observations_computed_against_previous(self, _clean_table, auth_client):
        # Snapshot N-1 : 100 publications
        prev = _sample_payload(sources=["hal"], phases=["extract"], duration=10.0)
        prev["observables"]["volumes"]["publications"] = 100
        with _conn() as cur:
            cur.execute(
                "INSERT INTO pipeline_run_snapshots (ran_at, mode, payload) "
                "VALUES (now() - interval '1 hour', 'full', %s::jsonb)",
                (json.dumps(prev),),
            )
            # Snapshot N : 1000 publications (×10, delta très au-dessus du seuil)
            curr = _sample_payload(sources=["hal"], phases=["extract"], duration=20.0)
            curr["observables"]["volumes"]["publications"] = 1000
            cur.execute(
                "INSERT INTO pipeline_run_snapshots (mode, payload) "
                "VALUES ('full', %s::jsonb) RETURNING id",
                (json.dumps(curr),),
            )
            run_id = cur.fetchone()["id"]

        r = auth_client.get(f"/api/admin/pipeline-runs/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["previous_snapshot_at"] is not None
        # L'observation `volumes.publications` doit être suspecte
        pubs_obs = next(o for o in body["observations"] if o["key"] == "volumes.publications")
        assert pubs_obs["suspect"] is True
        assert pubs_obs["previous"] == 100

    def test_unknown_id_returns_404(self, _clean_table, auth_client):
        r = auth_client.get("/api/admin/pipeline-runs/999999")
        assert r.status_code == 404
