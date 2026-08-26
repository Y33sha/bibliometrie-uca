"""Tests d'intégration de l'endpoint de log de phase du router `interfaces.api.routers.pipeline_runs`.

Couvre GET /api/pipeline/runs/{run_id}/phases/{phase}/log : découpe de la section, fichier absent, section absente. La lecture exige une session d'administration, d'où `auth_client` ; le refus qu'elle oppose sans session est couvert par `test_pipeline_runs_api`.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def _isolate_paths(tmp_path, monkeypatch):
    """Redirige le chemin du log de pipeline vers un dossier temp."""
    import infrastructure.observability.phase_logs as pl

    monkeypatch.setattr(pl, "PIPELINE_LOG", tmp_path / "pipeline.log")
    return tmp_path


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

    def test_returns_phase_slice(self, auth_client, _isolate_paths):
        self._write_log(_isolate_paths / "pipeline.log")
        r = auth_client.get("/api/pipeline/runs/5/phases/extract/log")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert "extract line" in body["content"]
        assert "normalize line" not in body["content"]

    def test_unavailable_when_file_missing(self, auth_client, _isolate_paths):
        # Pas de pipeline.log (LOG_TO_FILE désactivé).
        r = auth_client.get("/api/pipeline/runs/5/phases/extract/log")
        assert r.status_code == 200
        assert r.json() == {"available": False, "content": "", "omitted_lines": 0}

    def test_unavailable_when_section_absent(self, auth_client, _isolate_paths):
        self._write_log(_isolate_paths / "pipeline.log")
        r = auth_client.get("/api/pipeline/runs/5/phases/subjects/log")
        assert r.status_code == 200
        assert r.json() == {"available": False, "content": "", "omitted_lines": 0}
