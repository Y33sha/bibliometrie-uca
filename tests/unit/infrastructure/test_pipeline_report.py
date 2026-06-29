"""Tests de la capture/rapport pipeline (`infrastructure/observability/pipeline_report.py`)."""

import importlib.util
from pathlib import Path


def _fresh_module(tmp_path: Path, monkeypatch):
    """Recharge pipeline_report avec PROJECT_ROOT / LOGS_ROOT / REPORTS_DIR pointés vers tmp_path."""
    import infrastructure.observability.pipeline_report as pm

    spec = importlib.util.spec_from_file_location("pm_fresh", pm.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    monkeypatch.setattr(fresh, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fresh, "LOGS_ROOT", tmp_path / "logs")
    monkeypatch.setattr(fresh, "REPORTS_DIR", tmp_path / "logs" / "reports")
    return fresh


class TestIterLogFiles:
    def test_empty_tree(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        assert pm._iter_log_files() == []

    def test_collects_nested_logs(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs" / "a").mkdir(parents=True)
        (tmp_path / "logs" / "a" / "x.log").write_text("x")
        (tmp_path / "logs" / "b" / "c").mkdir(parents=True)
        (tmp_path / "logs" / "b" / "c" / "y.log").write_text("y")
        files = sorted(pm._iter_log_files())
        assert [f.name for f in files] == ["x.log", "y.log"]

    def test_excludes_cron_and_zenodo(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs").mkdir(parents=True)
        (tmp_path / "logs" / "cron.log").write_text("c")
        (tmp_path / "logs" / "zenodo.log").write_text("z")
        (tmp_path / "logs" / "normal.log").write_text("n")
        names = {f.name for f in pm._iter_log_files()}
        assert names == {"normal.log"}

    def test_excludes_reports_subtree(self, tmp_path, monkeypatch):
        """Les fichiers sous logs/reports/ sont ignorés (hébergent des .md)."""
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs" / "reports").mkdir(parents=True)
        (tmp_path / "logs" / "reports" / "bogus.log").write_text("no")
        (tmp_path / "logs" / "normal.log").write_text("yes")
        names = {f.name for f in pm._iter_log_files()}
        assert names == {"normal.log"}


class TestCaptureAndReadNewLogs:
    def test_capture_returns_current_sizes(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs").mkdir()
        f = tmp_path / "logs" / "x.log"
        f.write_text("hello")
        offsets = pm.capture_log_offsets()
        assert offsets == {str(f): 5}

    def test_read_new_logs_captures_only_appended(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs" / "sub").mkdir(parents=True)
        f = tmp_path / "logs" / "sub" / "y.log"
        f.write_text("old_content\n")

        offsets = pm.capture_log_offsets()
        f.write_text("old_content\nnew_line\n")

        out = pm.read_new_logs(offsets)
        assert "new_line" in out
        assert "old_content" not in out
        assert "### logs/sub/y.log" in out

    def test_read_new_logs_empty_if_no_change(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs").mkdir()
        f = tmp_path / "logs" / "x.log"
        f.write_text("hello")
        offsets = pm.capture_log_offsets()
        assert pm.read_new_logs(offsets) == ""

    def test_read_new_logs_handles_new_file(self, tmp_path, monkeypatch):
        """Un fichier créé après capture n'est pas dans offsets → lu entièrement."""
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs").mkdir()
        offsets = pm.capture_log_offsets()
        (tmp_path / "logs" / "new.log").write_text("fresh content")
        out = pm.read_new_logs(offsets)
        assert "fresh content" in out


class TestGenerateReport:
    def test_writes_markdown_under_logs_reports(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        phases = [
            ("extract", 12.5, "### logs/foo.log\n```\nwork\n```"),
            ("normalize", 3.0, ""),
        ]
        path = pm.generate_report("full", {"hal", "openalex"}, phases, 42.1)
        p = Path(path)
        assert p.exists()
        assert p.parent == tmp_path / "logs" / "reports"
        content = p.read_text(encoding="utf-8")
        assert "Rapport pipeline" in content
        assert "full" in content
        assert "hal" in content and "openalex" in content
        assert "extract (12.5s)" in content
        assert "<details>" in content  # logs détaillés inclus pour extract
        assert "normalize (3.0s)" in content
