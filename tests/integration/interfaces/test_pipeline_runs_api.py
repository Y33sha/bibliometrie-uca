"""Tests d'intégration du router des runs du pipeline (`/api/pipeline/runs/*`).

Couvre :
- GET /api/pipeline/runs (liste agrégée par run, statut global, ordre)
- GET /api/pipeline/runs/{run_id} (phases ordonnées, volumes avant et après, indicateurs par source, médiane historique et écart de durée ; statut warning ; 404)
"""

from __future__ import annotations

import pytest

from pipeline.public import PHASE_ORDER
from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import seed_phase_execution


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
    with owner_pool() as cur:
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
    seed_phase_execution(
        run_id,
        phase=phase,
        mode="full",
        status=status,
        sources=["hal", "openalex"],
        signals=signals or [],
        metrics=_metrics(duration_s),
        details=details or {},
    )


@pytest.fixture(scope="module")
def seeded_runs() -> dict[str, int]:
    """Sème deux runs : A sans warning ; B avec une phase en warning et une phase `publications` plus lente."""
    publications_details = {"tables": {"source_records": {"before": 1000, "after": 800}}}

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
    # Statut de chaque phase, dans l'ordre d'exécution.
    assert [p["phase"] for p in run_b["phases"]] == ["normalize", "publications", "persons"]
    assert run_b["phases"][2] == {"phase": "persons", "status": "warning"}

    # Plus récent (run_id plus grand) en premier.
    ids = [r["run_id"] for r in runs]
    assert ids.index(seeded_runs["b"]) < ids.index(seeded_runs["a"])


def test_list_phases(client):
    assert client.get("/api/pipeline/phases").json() == list(PHASE_ORDER)


def test_get_run_detail(client, seeded_runs):
    detail = client.get(f"/api/pipeline/runs/{seeded_runs['b']}").json()
    assert detail["status"] == "warning"
    assert [p["phase"] for p in detail["phases"]] == ["normalize", "publications", "persons"]

    publications = next(p for p in detail["phases"] if p["phase"] == "publications")
    # Volumes avant et après renvoyés tels quels dans `details`.
    assert publications["details"]["tables"]["source_records"] == {
        "before": 1000,
        "after": 800,
    }
    # Médiane historique : durée de `publications` dans le run A (10 s), hors run courant.
    assert publications["historical_median_duration_s"] == 10.0
    assert publications["duration_ratio"] == 2.0

    # Indicateurs par source renvoyés tels quels.
    normalize = next(p for p in detail["phases"] if p["phase"] == "normalize")
    assert normalize["details"]["by_source"]["openalex"]["found"] == 7658

    persons = next(p for p in detail["phases"] if p["phase"] == "persons")
    assert persons["status"] == "warning"
    assert persons["signals"][0]["code"] == "identity_conflict"


def test_get_run_404(client):
    assert client.get("/api/pipeline/runs/999999999").status_code == 404
