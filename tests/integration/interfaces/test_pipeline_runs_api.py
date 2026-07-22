"""Tests d'intégration pour le router `pipeline_runs` (`/api/pipeline/runs/*`).

Couvre :
- GET /api/pipeline/runs (liste agrégée par run, statut global, ordre)
- GET /api/pipeline/runs/{run_id} (phases ordonnées, details avant/après et
  by_source, médian de durée historique, écart de durée ; statut warning ; 404)
"""

from __future__ import annotations

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
def _pool():
    conn = psycopg.connect(**_DB_ARGS, row_factory=dict_row)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def _metrics(duration_s: float) -> dict:
    return {
        "new": 0,
        "updated": 0,
        "unchanged": 0,
        "total": 0,
        "errors": 0,
        "extras": {},
        "duration_s": duration_s,
    }


def _next_run_id() -> int:
    with _pool() as cur:
        cur.execute("SELECT nextval('pipeline_run_id_seq') AS id")
        return cur.fetchone()["id"]


def _seed_phase(
    run_id: int,
    phase: str,
    *,
    status: str,
    duration_s: float,
    details: dict | None = None,
    signals: list | None = None,
) -> None:
    with _pool() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_phase_executions
                (run_id, phase, started_at, ended_at, mode, sources, status,
                 signals, metrics, details)
            VALUES
                (%s, %s, now(), now(), %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
            """,
            (
                run_id,
                phase,
                "full",
                ["hal", "openalex"],
                status,
                json.dumps(signals or []),
                json.dumps(_metrics(duration_s)),
                json.dumps(details or {}),
            ),
        )


@pytest.fixture(scope="module")
def seeded_runs() -> dict[str, int]:
    """Deux runs : A tout vert, B avec une phase en warning et publications plus lente."""
    publications_details = {"tables": {"source_publications": {"before": 1000, "after": 800}}}

    run_a = _next_run_id()
    _seed_phase(run_a, "normalize", status="ok", duration_s=5.0)
    _seed_phase(run_a, "publications", status="ok", duration_s=10.0, details=publications_details)

    run_b = _next_run_id()
    _seed_phase(
        run_b,
        "normalize",
        status="ok",
        duration_s=6.0,
        details={
            "by_source": {
                "openalex": {
                    "found": 7658,
                    "new": 457,
                    "updated": 10,
                    "unchanged": 7191,
                    "errors": 0,
                    "duration_s": 42.0,
                }
            }
        },
    )
    _seed_phase(run_b, "publications", status="ok", duration_s=20.0, details=publications_details)
    _seed_phase(
        run_b,
        "persons",
        status="warning",
        duration_s=3.0,
        signals=[{"level": "warning", "code": "identity_conflict", "message": "doublon probable"}],
    )
    return {"a": run_a, "b": run_b}


def test_list_runs_aggrege_et_ordonne(client, seeded_runs):
    runs = client.get("/api/pipeline/runs?limit=200").json()
    by_id = {r["run_id"]: r for r in runs}
    assert seeded_runs["a"] in by_id
    assert seeded_runs["b"] in by_id

    run_a = by_id[seeded_runs["a"]]
    assert run_a["status"] == "ok"
    assert run_a["phase_count"] == 2
    assert run_a["total_duration_s"] == 15.0
    assert run_a["sources"] == ["hal", "openalex"]

    run_b = by_id[seeded_runs["b"]]
    assert run_b["status"] == "warning"
    assert run_b["phase_count"] == 3
    # Ruban : statut par phase, dans l'ordre d'exécution.
    assert [p["phase"] for p in run_b["phases"]] == ["normalize", "publications", "persons"]
    assert run_b["phases"][2] == {"phase": "persons", "status": "warning"}

    # Plus récent (run_id plus grand) en premier.
    ids = [r["run_id"] for r in runs]
    assert ids.index(seeded_runs["b"]) < ids.index(seeded_runs["a"])


def test_list_phases(client):
    phases = client.get("/api/pipeline/phases").json()
    assert phases[0] == "extract"
    assert "normalize" in phases
    assert phases[-1] == "oa_status"
    assert len(phases) == 16


def test_get_run_detail(client, seeded_runs):
    detail = client.get(f"/api/pipeline/runs/{seeded_runs['b']}").json()
    assert detail["status"] == "warning"
    assert [p["phase"] for p in detail["phases"]] == ["normalize", "publications", "persons"]

    publications = next(p for p in detail["phases"] if p["phase"] == "publications")
    # Volumes avant/après conservés tels quels dans details (pas de ratio de rendement).
    assert publications["details"]["tables"]["source_publications"] == {
        "before": 1000,
        "after": 800,
    }
    # Médian historique = durée de publications dans run A (10), run courant exclu.
    assert publications["historical_median_duration_s"] == 10.0
    assert publications["duration_ratio"] == 2.0

    # Indicateur sur-mesure par source remonté tel quel.
    normalize = next(p for p in detail["phases"] if p["phase"] == "normalize")
    assert normalize["details"]["by_source"]["openalex"]["found"] == 7658

    persons = next(p for p in detail["phases"] if p["phase"] == "persons")
    assert persons["status"] == "warning"
    assert persons["signals"][0]["code"] == "identity_conflict"


def test_get_run_404(client):
    assert client.get("/api/pipeline/runs/999999999").status_code == 404
