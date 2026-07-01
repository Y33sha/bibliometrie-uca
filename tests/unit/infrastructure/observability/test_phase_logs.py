"""Tests unitaires du découpage du log par phase (`slice_phase_log`).

Fonction pure sur un texte de log : pas de fichier ni de base.
"""

from __future__ import annotations

from infrastructure.observability.phase_logs import slice_phase_log

# Deux runs concaténés dans un même fichier append-only, format texte.
LOG = "\n".join(
    [
        "2026-07-01 09:00:00,000 [INFO] pipeline: Run pipeline #4",
        "2026-07-01 09:00:00,001 [INFO] pipeline: PHASE : extract",
        "2026-07-01 09:00:01,000 [INFO] pipeline: extract source hal",
        "2026-07-01 09:00:02,000 [INFO] pipeline: PHASE : normalize",
        "2026-07-01 09:00:03,000 [INFO] pipeline: normalize done",
        "2026-07-01 09:00:04,000 [INFO] pipeline: PIPELINE TERMINÉ en 4s",
        "2026-07-01 14:00:00,000 [INFO] pipeline: Run pipeline #5",
        "2026-07-01 14:00:00,001 [INFO] pipeline: PHASE : extract",
        "2026-07-01 14:00:01,000 [INFO] pipeline: extract run 5",
        "2026-07-01 14:00:02,000 [INFO] pipeline: PHASE : publishers_journals",
        "2026-07-01 14:00:03,000 [INFO] pipeline: publishers run 5",
        "2026-07-01 14:00:04,000 [INFO] pipeline: PIPELINE TERMINÉ en 4s",
    ]
)


def test_slices_phase_bounded_by_next_phase():
    out = slice_phase_log(LOG, run_id=4, phase="extract")
    assert out is not None
    lines = out.splitlines()
    assert "PHASE : extract" in lines[0]
    assert any("extract source hal" in line for line in lines)
    # Borne : la phase suivante est exclue.
    assert all("normalize" not in line for line in lines)


def test_slices_phase_bounded_by_run_end():
    out = slice_phase_log(LOG, run_id=4, phase="normalize")
    assert out is not None
    assert "normalize done" in out
    assert "PIPELINE TERMINÉ" not in out


def test_selects_the_right_run():
    # `extract` existe dans les deux runs : on isole celui du run demandé.
    out = slice_phase_log(LOG, run_id=5, phase="extract")
    assert out is not None
    assert "extract run 5" in out
    assert "extract source hal" not in out


def test_run_marker_is_not_a_prefix_match():
    # `#5` ne doit pas matcher `#50` (ni l'inverse) : ancrage strict du run_id.
    log = LOG.replace("Run pipeline #5", "Run pipeline #50")
    assert slice_phase_log(log, run_id=5, phase="extract") is None


def test_phase_marker_is_not_a_prefix_match():
    # `PHASE : publishers` ne doit pas matcher `PHASE : publishers_journals`.
    assert slice_phase_log(LOG, run_id=5, phase="publishers") is None


def test_running_phase_slices_to_end_of_text():
    # Run en cours : la dernière phase n'a pas de borne de fin → jusqu'à EOF.
    partial = "\n".join(
        [
            "2026-07-01 15:00:00,000 [INFO] pipeline: Run pipeline #6",
            "2026-07-01 15:00:00,001 [INFO] pipeline: PHASE : extract",
            "2026-07-01 15:00:01,000 [INFO] pipeline: extract in progress",
        ]
    )
    out = slice_phase_log(partial, run_id=6, phase="extract")
    assert out is not None
    assert "extract in progress" in out


def test_unknown_run_returns_none():
    assert slice_phase_log(LOG, run_id=99, phase="extract") is None


def test_unknown_phase_returns_none():
    assert slice_phase_log(LOG, run_id=4, phase="subjects") is None


def test_works_on_json_formatted_lines():
    # Les marqueurs vivent dans le message : le découpage marche aussi en JSON.
    log = "\n".join(
        [
            '{"level": "INFO", "logger": "pipeline", "message": "Run pipeline #7"}',
            '{"level": "INFO", "logger": "pipeline", "message": "PHASE : normalize"}',
            '{"level": "INFO", "logger": "pipeline", "message": "normalize json run"}',
            '{"level": "INFO", "logger": "pipeline", "message": "PIPELINE TERMINÉ en 1s"}',
        ]
    )
    out = slice_phase_log(log, run_id=7, phase="normalize")
    assert out is not None
    assert "normalize json run" in out
    assert "TERMINÉ" not in out
