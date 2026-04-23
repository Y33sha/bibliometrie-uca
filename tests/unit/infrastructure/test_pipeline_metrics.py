"""Tests de la capture/rapport pipeline (infrastructure/pipeline_metrics.py)."""

import importlib.util
from pathlib import Path


def _fresh_module(tmp_path: Path, monkeypatch):
    """Recharge pipeline_metrics avec BASE pointée vers tmp_path."""
    import infrastructure.pipeline_metrics as pm

    spec = importlib.util.spec_from_file_location("pm_fresh", pm.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    monkeypatch.setattr(fresh, "BASE", tmp_path)
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

    def test_sandbox_label(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        monkeypatch.setenv("BIBLIOMETRIE_SANDBOX", "1")
        path = pm.generate_report("full", {"hal"}, [], 1.0)
        p = Path(path)
        assert p.parent == tmp_path / "logs" / "reports" / "sandbox"
        assert "(SANDBOX)" in p.read_text(encoding="utf-8")


class TestGetLastReportDate:
    def test_none_when_dir_missing(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        assert pm.get_last_report_date() is None

    def test_none_when_no_reports(self, tmp_path, monkeypatch):
        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs" / "reports").mkdir(parents=True)
        assert pm.get_last_report_date() is None

    def test_returns_max_date_across_reports(self, tmp_path, monkeypatch):
        import datetime

        pm = _fresh_module(tmp_path, monkeypatch)
        reports = tmp_path / "logs" / "reports"
        reports.mkdir(parents=True)
        (reports / "2026-03-01_101010.md").write_text("")
        (reports / "2026-04-15_200000.md").write_text("")
        (reports / "2026-04-15_091500.md").write_text("")
        assert pm.get_last_report_date() == datetime.date(2026, 4, 15)

    def test_ignores_unparseable_filenames(self, tmp_path, monkeypatch):
        import datetime

        pm = _fresh_module(tmp_path, monkeypatch)
        reports = tmp_path / "logs" / "reports"
        reports.mkdir(parents=True)
        (reports / "2026-02-10_000000.md").write_text("")
        (reports / "README.md").write_text("")
        (reports / "bogus-name.md").write_text("")
        assert pm.get_last_report_date() == datetime.date(2026, 2, 10)

    def test_sandbox_isolated_from_prod(self, tmp_path, monkeypatch):
        import datetime

        pm = _fresh_module(tmp_path, monkeypatch)
        (tmp_path / "logs" / "reports").mkdir(parents=True)
        (tmp_path / "logs" / "reports" / "2026-04-20_120000.md").write_text("")
        (tmp_path / "logs" / "reports" / "sandbox").mkdir()
        (tmp_path / "logs" / "reports" / "sandbox" / "2026-04-22_120000.md").write_text("")
        # Sans sandbox → lit logs/reports/
        assert pm.get_last_report_date() == datetime.date(2026, 4, 20)
        # Avec sandbox → lit logs/reports/sandbox/
        monkeypatch.setenv("BIBLIOMETRIE_SANDBOX", "1")
        assert pm.get_last_report_date() == datetime.date(2026, 4, 22)
