"""Tests de la consolidation des logs (infrastructure/log.py)."""

from infrastructure.log import _PROJECT_ROOT, _rebase_log_dir


class TestRebaseLogDir:
    def test_absolute_path_under_project(self):
        """Caller interne : reproduit l'arborescence sous logs/."""
        result = _rebase_log_dir(str(_PROJECT_ROOT / "infrastructure" / "sources" / "hal" / "logs"))
        assert result == _PROJECT_ROOT / "logs" / "infrastructure" / "sources" / "hal"

    def test_relative_path(self):
        """Chemin relatif : résolu par rapport à la racine."""
        result = _rebase_log_dir("processing/logs")
        assert result == _PROJECT_ROOT / "logs" / "processing"

    def test_strips_trailing_logs_only(self):
        """Seul le 'logs' final est supprimé, pas les autres segments intermédiaires."""
        result = _rebase_log_dir(str(_PROJECT_ROOT / "a" / "logs" / "b" / "logs"))
        assert result == _PROJECT_ROOT / "logs" / "a" / "logs" / "b"

    def test_no_logs_suffix(self):
        """Si pas de suffixe 'logs', tout est conservé."""
        result = _rebase_log_dir(str(_PROJECT_ROOT / "some" / "dir"))
        assert result == _PROJECT_ROOT / "logs" / "some" / "dir"

    def test_outside_project(self, tmp_path):
        """Chemin hors du projet : replié sous logs/ avec ses segments nommés."""
        external = tmp_path / "other" / "logs"
        result = _rebase_log_dir(str(external))
        # On attend que le rebase fallback ait construit un chemin sous logs/
        assert _PROJECT_ROOT / "logs" in [result, *result.parents]

    def test_just_logs(self):
        """log_dir = 'logs' seul : résultat = PROJECT_ROOT/logs."""
        result = _rebase_log_dir(str(_PROJECT_ROOT / "logs"))
        assert result == _PROJECT_ROOT / "logs"


class TestSetupLoggerFileLocation:
    """Valide que setup_logger (version d'origine) écrit sous logs/<relpath>/.

    conftest.py remplace setup_logger par un stub NullHandler pour éviter
    la pollution disque en tests. On recharge la vraie implémentation
    via importlib.util.
    """

    def test_writes_under_logs_tree(self, tmp_path, monkeypatch):
        import importlib.util

        import infrastructure.log as log_module

        spec = importlib.util.spec_from_file_location(
            "infrastructure_log_fresh", log_module.__file__
        )
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        monkeypatch.setattr(fresh, "_PROJECT_ROOT", tmp_path)

        logger = fresh.setup_logger("pytest_fake_logger", str(tmp_path / "foo" / "bar" / "logs"))
        try:
            logger.info("marker")
            for h in logger.handlers:
                h.flush()
            expected = tmp_path / "logs" / "foo" / "bar" / "pytest_fake_logger.log"
            assert expected.exists()
            assert "marker" in expected.read_text(encoding="utf-8")
        finally:
            for h in list(logger.handlers):
                h.close()
                logger.removeHandler(h)


class TestMakeFormatter:
    def test_json_default(self):
        import logging as _logging

        from infrastructure.log import _make_formatter

        fmt = _make_formatter()
        record = _logging.LogRecord(
            name="t",
            level=_logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=None,
            exc_info=None,
        )
        line = fmt.format(record)
        assert line.startswith("{") and '"message": "hello"' in line

    def test_text_when_env_text(self, monkeypatch):
        import logging as _logging

        from infrastructure.log import _make_formatter

        monkeypatch.setenv("LOG_FORMAT", "text")
        fmt = _make_formatter()
        record = _logging.LogRecord(
            name="t",
            level=_logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=None,
            exc_info=None,
        )
        line = fmt.format(record)
        assert "hello" in line and "INFO" in line and not line.startswith("{")


class TestJsonFormatter:
    def test_merges_extras(self):
        import json
        import logging as _logging

        from infrastructure.log import JsonFormatter

        fmt = JsonFormatter()
        record = _logging.LogRecord(
            name="t",
            level=_logging.INFO,
            pathname="",
            lineno=0,
            msg="payload",
            args=None,
            exc_info=None,
        )
        record.foo = "bar"  # extra
        data = json.loads(fmt.format(record))
        assert data["foo"] == "bar"
        assert data["message"] == "payload"
        assert data["level"] == "INFO"

    def test_formats_exception(self):
        import json
        import logging as _logging
        import sys as _sys

        from infrastructure.log import JsonFormatter

        fmt = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = _sys.exc_info()
        record = _logging.LogRecord(
            name="t",
            level=_logging.ERROR,
            pathname="",
            lineno=0,
            msg="fail",
            args=None,
            exc_info=exc_info,
        )
        data = json.loads(fmt.format(record))
        assert "ValueError: boom" in data["exception"]


class TestConfigureRootLogging:
    def test_replaces_handlers(self, monkeypatch):
        """Sans pytest dans l'env, un StreamHandler est attaché au root."""
        import logging as _logging

        # Retirer le marqueur pytest pour exercer la branche "prod"
        monkeypatch.delenv("PYTEST_VERSION", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from infrastructure.log import configure_root_logging

        root = _logging.getLogger()
        dummy = _logging.NullHandler()
        root.addHandler(dummy)
        try:
            configure_root_logging()
            assert dummy not in root.handlers
            assert len(root.handlers) == 1
            assert root.level == _logging.INFO
        finally:
            for h in list(root.handlers):
                root.removeHandler(h)

    def test_skips_handler_under_pytest(self, monkeypatch):
        """Sous pytest, aucun StreamHandler n'est attaché : pytest a son
        propre LogCaptureHandler, attacher en plus polluerait la sortie
        des tests (duplications, échappement de la capture)."""
        import logging as _logging

        monkeypatch.setenv("PYTEST_VERSION", "test")

        from infrastructure.log import configure_root_logging

        root = _logging.getLogger()
        dummy = _logging.NullHandler()
        root.addHandler(dummy)
        try:
            configure_root_logging()
            assert dummy not in root.handlers
            assert len(root.handlers) == 0
        finally:
            for h in list(root.handlers):
                root.removeHandler(h)
