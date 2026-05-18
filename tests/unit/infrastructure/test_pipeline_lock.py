"""Tests unitaires du lock pipeline (`infrastructure.pipeline_lock`).

Vérifie :
- Lockfile absent → acquisition transparente.
- Lockfile orphelin (PID mort) → écrasement silencieux.
- Lockfile vivant + force=False → PipelineAlreadyRunningError.
- Lockfile vivant + force=True → SIGTERM (puis SIGKILL en fallback) + acquisition.
- release_pipeline_lock supprime seulement si on est le owner.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from infrastructure.pipeline_lock import (
    PipelineAlreadyRunningError,
    acquire_pipeline_lock,
    release_pipeline_lock,
)


@pytest.fixture
def lockfile(tmp_path: Path) -> Path:
    return tmp_path / "pipeline.lock"


class TestAcquire:
    def test_no_existing_lockfile(self, lockfile: Path) -> None:
        acquire_pipeline_lock(lockfile=lockfile)
        assert lockfile.read_text() == str(os.getpid())

    def test_orphan_lockfile_is_overwritten(self, lockfile: Path) -> None:
        # PID 999999 : pratiquement garanti de ne pas exister (pid_max usuellement < 100k)
        lockfile.write_text("999999")
        acquire_pipeline_lock(lockfile=lockfile)
        assert lockfile.read_text() == str(os.getpid())

    def test_corrupted_lockfile_is_overwritten(self, lockfile: Path) -> None:
        lockfile.write_text("not-a-pid")
        acquire_pipeline_lock(lockfile=lockfile)
        assert lockfile.read_text() == str(os.getpid())

    def test_alive_lockfile_aborts_without_force(self, lockfile: Path) -> None:
        # On simule un PID vivant en mettant notre propre PID (qui est forcément vivant)
        lockfile.write_text("1")  # PID 1 (init) — toujours vivant
        with patch("infrastructure.pipeline_lock._process_alive", return_value=True):
            with pytest.raises(PipelineAlreadyRunningError, match=r"PID 1"):
                acquire_pipeline_lock(lockfile=lockfile, force=False)
        # Lockfile préservé : on n'écrase pas un lock actif sans permission.
        assert lockfile.read_text() == "1"

    def test_alive_lockfile_force_kills_and_takes_over(self, lockfile: Path) -> None:
        lockfile.write_text("12345")

        kill_calls: list[tuple[int, int]] = []

        def fake_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))

        # _process_alive : True d'abord (détecté à l'acquisition), puis False
        # immédiatement après SIGTERM (le précédent répond proprement).
        alive_responses = iter([True, False])

        def fake_process_alive(pid: int) -> bool:
            return next(alive_responses)

        with (
            patch("infrastructure.pipeline_lock._process_alive", side_effect=fake_process_alive),
            patch("infrastructure.pipeline_lock.os.kill", side_effect=fake_kill),
            patch("infrastructure.pipeline_lock.time.sleep"),
        ):
            acquire_pipeline_lock(lockfile=lockfile, force=True)

        # SIGTERM envoyé une fois, pas de SIGKILL nécessaire (process mort dans le grace).
        assert kill_calls == [(12345, 15)]  # signal.SIGTERM = 15
        assert lockfile.read_text() == str(os.getpid())

    def test_alive_lockfile_force_falls_back_to_sigkill(self, lockfile: Path) -> None:
        lockfile.write_text("12345")

        kill_calls: list[tuple[int, int]] = []

        def fake_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))

        # Le process ne meurt jamais après SIGTERM → SIGKILL en fallback.
        with (
            patch("infrastructure.pipeline_lock._process_alive", return_value=True),
            patch("infrastructure.pipeline_lock.os.kill", side_effect=fake_kill),
            patch("infrastructure.pipeline_lock.time.sleep"),
        ):
            acquire_pipeline_lock(lockfile=lockfile, force=True)

        # SIGTERM (15) puis SIGKILL (9).
        assert kill_calls == [(12345, 15), (12345, 9)]
        assert lockfile.read_text() == str(os.getpid())


class TestRelease:
    def test_release_removes_own_lockfile(self, lockfile: Path) -> None:
        lockfile.write_text(str(os.getpid()))
        release_pipeline_lock(lockfile=lockfile)
        assert not lockfile.exists()

    def test_release_keeps_other_owner_lockfile(self, lockfile: Path) -> None:
        # Lock détenu par un autre PID — on ne doit pas le retirer (cas où
        # on a été SIGKILL et un nouveau pipeline a déjà pris le lock).
        lockfile.write_text("99999")
        release_pipeline_lock(lockfile=lockfile)
        assert lockfile.exists()
        assert lockfile.read_text() == "99999"

    def test_release_is_idempotent_when_lockfile_missing(self, lockfile: Path) -> None:
        # Pas de lockfile : pas d'erreur.
        release_pipeline_lock(lockfile=lockfile)
        assert not lockfile.exists()
