"""Tests d'intégration pour le router `interfaces.api.routers.admin.pipeline_logs`.

Couvre :
- GET /api/pipeline/status (avec / sans pipeline en cours)
- GET /api/pipeline/runs/{run_id}/phases/{phase}/log (découpe, fichier absent)
"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture
def _isolate_paths(tmp_path, monkeypatch):
    """Redirige les chemins disque des routers vers un dossier temp."""
    import infrastructure.observability.phase_logs as pl
    import infrastructure.observability.pipeline_status as ps

    monkeypatch.setattr(ps, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(pl, "PIPELINE_LOG", tmp_path / "pipeline.log")
    return tmp_path


class TestPipelineStatus:
    def test_returns_null_when_no_status_file(self, client, _isolate_paths):
        r = client.get("/api/pipeline/status")
        assert r.status_code == 200
        assert r.json() is None

    def test_returns_status_when_alive(self, client, _isolate_paths, monkeypatch):
        # `read_status` valide le PID — on stub `is_pid_alive` pour
        # éviter de devoir spawner un vrai process.
        import infrastructure.observability.pipeline_status as ps

        monkeypatch.setattr(ps, "is_pid_alive", lambda pid: True)

        status_file = _isolate_paths / "status.json"
        status_file.write_text(
            json.dumps(
                {
                    "mode": "full",
                    "phase": "extract",
                    "started_at": "2026-05-17T10:00:00",
                    "phase_started_at": "2026-05-17T10:00:00",
                    "phases_done": 0,
                    "phases_total": 10,
                    "pid": os.getpid(),
                }
            ),
            encoding="utf-8",
        )

        r = client.get("/api/pipeline/status")
        assert r.status_code == 200
        body = r.json()
        assert body is not None
        assert body["mode"] == "full"
        assert body["phase"] == "extract"


class TestPhaseLog:
    def _write_log(self, path):
        path.write_text(
            "\n".join(
                [
                    "2026-07-01 14:00:00,000 [INFO] pipeline: Run pipeline #5",
                    "2026-07-01 14:00:00,001 [INFO] pipeline: PHASE : extract",
                    "2026-07-01 14:00:01,000 [INFO] pipeline: extract line",
                    "2026-07-01 14:00:02,000 [INFO] pipeline: PHASE : normalize",
                    "2026-07-01 14:00:03,000 [INFO] pipeline: normalize line",
                    "2026-07-01 14:00:04,000 [INFO] pipeline: PIPELINE TERMINÉ en 4s",
                ]
            ),
            encoding="utf-8",
        )

    def test_returns_phase_slice(self, client, _isolate_paths):
        self._write_log(_isolate_paths / "pipeline.log")
        r = client.get("/api/pipeline/runs/5/phases/extract/log")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert "extract line" in body["content"]
        assert "normalize line" not in body["content"]

    def test_unavailable_when_file_missing(self, client, _isolate_paths):
        # Pas de pipeline.log (LOG_TO_FILE désactivé).
        r = client.get("/api/pipeline/runs/5/phases/extract/log")
        assert r.status_code == 200
        assert r.json() == {"available": False, "content": ""}

    def test_unavailable_when_section_absent(self, client, _isolate_paths):
        self._write_log(_isolate_paths / "pipeline.log")
        r = client.get("/api/pipeline/runs/5/phases/subjects/log")
        assert r.status_code == 200
        assert r.json() == {"available": False, "content": ""}
