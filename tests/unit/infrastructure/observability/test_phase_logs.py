"""Tests unitaires du découpage du log par phase (`slice_phase_log`).

Fonction pure sur une suite de lignes : pas de fichier ni de base.
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
    out = slice_phase_log(LOG.splitlines(), run_id=4, phase="extract")
    assert out is not None
    lines = out.content.splitlines()
    assert "PHASE : extract" in lines[0]
    assert any("extract source hal" in line for line in lines)
    # Borne : la phase suivante est exclue.
    assert all("normalize" not in line for line in lines)


def test_slices_phase_bounded_by_run_end():
    out = slice_phase_log(LOG.splitlines(), run_id=4, phase="normalize")
    assert out is not None
    assert "normalize done" in out.content
    assert "PIPELINE TERMINÉ" not in out.content


def test_selects_the_right_run():
    # `extract` existe dans les deux runs : on isole celui du run demandé.
    out = slice_phase_log(LOG.splitlines(), run_id=5, phase="extract")
    assert out is not None
    assert "extract run 5" in out.content
    assert "extract source hal" not in out.content


def test_run_marker_is_not_a_prefix_match():
    # `#5` ne doit pas matcher `#50` (ni l'inverse) : ancrage strict du run_id.
    log = LOG.replace("Run pipeline #5", "Run pipeline #50")
    assert slice_phase_log(log.splitlines(), run_id=5, phase="extract") is None


def test_phase_marker_is_not_a_prefix_match():
    # `PHASE : publishers` ne doit pas matcher `PHASE : publishers_journals`.
    assert slice_phase_log(LOG.splitlines(), run_id=5, phase="publishers") is None


def test_running_phase_slices_to_end_of_text():
    # Run en cours : la dernière phase n'a pas de borne de fin → jusqu'à EOF.
    partial = "\n".join(
        [
            "2026-07-01 15:00:00,000 [INFO] pipeline: Run pipeline #6",
            "2026-07-01 15:00:00,001 [INFO] pipeline: PHASE : extract",
            "2026-07-01 15:00:01,000 [INFO] pipeline: extract in progress",
        ]
    )
    out = slice_phase_log(partial.splitlines(), run_id=6, phase="extract")
    assert out is not None
    assert "extract in progress" in out.content


def test_unknown_run_returns_none():
    assert slice_phase_log(LOG.splitlines(), run_id=99, phase="extract") is None


def test_unknown_phase_returns_none():
    assert slice_phase_log(LOG.splitlines(), run_id=4, phase="subjects") is None


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
    out = slice_phase_log(log.splitlines(), run_id=7, phase="normalize")
    assert out is not None
    assert "normalize json run" in out.content
    assert "TERMINÉ" not in out.content


def test_long_section_keeps_the_end_and_counts_what_precedes():
    # Section plus longue que le plafond : les dernières lignes sont rendues, les
    # précédentes comptées — une troncature s'annonce.
    log = "\n".join(
        [
            "2026-07-01 16:00:00,000 [INFO] pipeline: Run pipeline #8",
            "2026-07-01 16:00:00,001 [INFO] pipeline: PHASE : persons",
            *[f"ligne {i}" for i in range(10)],
            "2026-07-01 16:00:05,000 [INFO] pipeline: PIPELINE TERMINÉ en 5s",
        ]
    )
    out = slice_phase_log(log.splitlines(), run_id=8, phase="persons", max_lines=4)
    assert out is not None
    assert out.content.splitlines() == ["ligne 6", "ligne 7", "ligne 8", "ligne 9"]
    # Le marqueur de phase et les six premières lignes sont hors de l'extrait.
    assert out.omitted_lines == 7


def test_section_within_the_cap_omits_nothing():
    out = slice_phase_log(LOG.splitlines(), run_id=4, phase="normalize", max_lines=100)
    assert out is not None
    assert out.omitted_lines == 0


def test_memory_is_bounded_by_the_cap_not_by_the_input():
    # Le fichier est parcouru en flux : un log immense ne fait pas grossir l'extrait.
    def _lines():
        yield "Run pipeline #9"
        yield "PHASE : extract"
        for i in range(100_000):
            yield f"ligne {i}"

    out = slice_phase_log(_lines(), run_id=9, phase="extract", max_lines=50)
    assert out is not None
    assert len(out.content.splitlines()) == 50
    assert out.omitted_lines == 100_000 - 49
