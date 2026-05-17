"""Tests d'intégration pour le router `interfaces.api.routers.admin_pipeline`.

Couvre :
- GET /api/admin/pipeline/status (avec / sans pipeline en cours)
- GET /api/admin/pipeline/logs (cron.log présent / absent, tail)
- GET /api/admin/pipeline/reports (liste, parsing nom de fichier)
- GET /api/admin/pipeline/reports/{filename} (404, 400 path traversal, .md required, happy)
"""

from __future__ import annotations

import json
import os

import pytest

from interfaces.api.routers import admin_pipeline


@pytest.fixture
def _isolate_paths(tmp_path, monkeypatch):
    """Redirige les chemins disque du router vers un dossier temp."""
    reports_dir = tmp_path / "reports"
    cron_log = tmp_path / "cron.log"
    status_file = tmp_path / "status.json"

    monkeypatch.setattr(admin_pipeline, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(admin_pipeline, "CRON_LOG", cron_log)

    import infrastructure.pipeline_status as ps

    monkeypatch.setattr(ps, "STATUS_FILE", status_file)
    return tmp_path


class TestPipelineStatus:
    def test_returns_null_when_no_status_file(self, client, _isolate_paths):
        r = client.get("/api/admin/pipeline/status")
        assert r.status_code == 200
        assert r.json() is None

    def test_returns_status_when_alive(self, client, _isolate_paths, monkeypatch):
        # `read_status` valide le PID — on stub `_is_pid_alive` pour
        # éviter de devoir spawner un vrai process.
        import infrastructure.pipeline_status as ps

        monkeypatch.setattr(ps, "_is_pid_alive", lambda pid: True)

        status_file = _isolate_paths / "status.json"
        status_file.write_text(
            json.dumps(
                {
                    "running": True,
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

        r = client.get("/api/admin/pipeline/status")
        assert r.status_code == 200
        body = r.json()
        assert body is not None
        assert body["mode"] == "full"
        assert body["phase"] == "extract"


class TestPipelineLogs:
    def test_returns_empty_when_log_missing(self, client, _isolate_paths):
        r = client.get("/api/admin/pipeline/logs")
        assert r.status_code == 200
        assert r.json() == {"content": ""}

    def test_returns_tail(self, client, _isolate_paths):
        cron_log = _isolate_paths / "cron.log"
        cron_log.write_text("\n".join(f"line {i}" for i in range(50)), encoding="utf-8")

        r = client.get("/api/admin/pipeline/logs", params={"lines": 5})
        assert r.status_code == 200
        # Tail = 5 dernières lignes
        content = r.json()["content"]
        assert content.splitlines() == ["line 45", "line 46", "line 47", "line 48", "line 49"]

    def test_default_lines_param(self, client, _isolate_paths):
        # Default `lines=200` : si le log a moins, on retourne tout.
        cron_log = _isolate_paths / "cron.log"
        cron_log.write_text("only one line", encoding="utf-8")
        r = client.get("/api/admin/pipeline/logs")
        assert r.status_code == 200
        assert r.json()["content"] == "only one line"


class TestListReports:
    def test_empty_when_dir_missing(self, client, _isolate_paths):
        # `REPORTS_DIR` n'existe pas du tout → []
        r = client.get("/api/admin/pipeline/reports")
        assert r.status_code == 200
        assert r.json() == []

    def test_lists_md_files_sorted_desc(self, client, _isolate_paths):
        reports_dir = _isolate_paths / "reports"
        reports_dir.mkdir()
        (reports_dir / "2026-05-16_120000.md").write_text("a", encoding="utf-8")
        (reports_dir / "2026-05-17_093000.md").write_text("b", encoding="utf-8")
        (reports_dir / "2026-05-15_080000.md").write_text("c", encoding="utf-8")

        r = client.get("/api/admin/pipeline/reports")
        assert r.status_code == 200
        items = r.json()
        # Tri reverse → plus récent d'abord
        assert [item["filename"] for item in items] == [
            "2026-05-17_093000.md",
            "2026-05-16_120000.md",
            "2026-05-15_080000.md",
        ]
        # Le label parse YYYY-MM-DD_HHMMSS → "YYYY-MM-DD HH:MM"
        assert items[0]["label"] == "2026-05-17 09:30"

    def test_falls_back_on_unparseable_stem(self, client, _isolate_paths):
        # Nom de fichier sans `_HHMMSS` : `stem.split("_", 1)` lève
        # ValueError → fallback sur le stem entier comme label.
        reports_dir = _isolate_paths / "reports"
        reports_dir.mkdir()
        (reports_dir / "weird-name.md").write_text("x", encoding="utf-8")

        r = client.get("/api/admin/pipeline/reports")
        assert r.status_code == 200
        items = r.json()
        assert items[0]["label"] == "weird-name"


class TestGetReport:
    def test_404_when_not_found(self, client, _isolate_paths):
        (_isolate_paths / "reports").mkdir()
        r = client.get("/api/admin/pipeline/reports/missing.md")
        assert r.status_code == 404

    def test_400_on_dotdot_in_filename(self, client, _isolate_paths):
        # Le check `".." in filename` est la seule branche du garde-fou
        # atteignable via routage normal : `/` et `\` dans l'URL sont
        # rejetés en 404 par le dispatcher Starlette avant d'arriver au
        # handler. Cas réaliste : un client malveillant essaie de passer
        # un nom contenant `..` sans slash (atypique mais possible).
        r = client.get("/api/admin/pipeline/reports/..hidden.md")
        assert r.status_code == 400

    def test_404_when_extension_not_md(self, client, _isolate_paths):
        reports_dir = _isolate_paths / "reports"
        reports_dir.mkdir()
        (reports_dir / "log.txt").write_text("content", encoding="utf-8")

        r = client.get("/api/admin/pipeline/reports/log.txt")
        assert r.status_code == 404

    def test_returns_content(self, client, _isolate_paths):
        reports_dir = _isolate_paths / "reports"
        reports_dir.mkdir()
        (reports_dir / "2026-05-17_090000.md").write_text(
            "# Pipeline report\nrun OK", encoding="utf-8"
        )

        r = client.get("/api/admin/pipeline/reports/2026-05-17_090000.md")
        assert r.status_code == 200
        body = r.json()
        assert body["filename"] == "2026-05-17_090000.md"
        assert body["content"] == "# Pipeline report\nrun OK"
