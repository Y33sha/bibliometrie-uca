"""Extraction du log d'une phase depuis ``logs/pipeline.log``.

L'orchestrateur écrit ses logs dans un fichier unique et append-only
(``logs/pipeline.log`` via ``setup_logger`` quand ``LOG_TO_FILE=true``). Les
runs et les phases y sont bornés par des marqueurs textuels stables, émis par
``run_pipeline.py`` :

- début de run : ``Run pipeline #<run_id>`` ;
- début de phase : ``PHASE : <nom>`` ;
- fin de run : ``PIPELINE TERMINÉ``.

Servir le log d'une phase revient donc à découper la section correspondante du
fichier, sans machinerie de capture dédiée ni stockage en base. Le découpage se
fait sur les marqueurs (présents quel que soit ``LOG_FORMAT``, texte ou JSON,
puisqu'ils vivent dans le message), pas sur les horodatages.
"""

from __future__ import annotations

import re

from infrastructure import PROJECT_ROOT

PIPELINE_LOG = PROJECT_ROOT / "logs" / "pipeline.log"

_RUN_MARKER = "Run pipeline #"
_PHASE_MARKER = "PHASE : "
_RUN_END_MARKER = "PIPELINE TERMINÉ"


def slice_phase_log(log_text: str, run_id: int, phase: str) -> str | None:
    """Section du log correspondant à ``phase`` dans le run ``run_id``.

    Renvoie ``None`` si le run ou la phase ne figure pas dans ``log_text``
    (log purgé, run antérieur au suivi, phase non jouée). La section court du
    marqueur ``PHASE : <phase>`` jusqu'au prochain début de phase, début de run
    ou fin de run (bornes exclues) ; pour un run encore en cours, jusqu'à la fin
    du texte.
    """
    lines = log_text.splitlines()
    run_re = re.compile(rf"{re.escape(_RUN_MARKER)}{run_id}(?!\d)")
    phase_re = re.compile(rf"{re.escape(_PHASE_MARKER)}{re.escape(phase)}\b")

    run_start = next((i for i, line in enumerate(lines) if run_re.search(line)), None)
    if run_start is None:
        return None

    phase_start = next((i for i in range(run_start, len(lines)) if phase_re.search(lines[i])), None)
    if phase_start is None:
        return None

    end = len(lines)
    for i in range(phase_start + 1, len(lines)):
        line = lines[i]
        if _PHASE_MARKER in line or _RUN_MARKER in line or _RUN_END_MARKER in line:
            end = i
            break
    return "\n".join(lines[phase_start:end])


def read_phase_log(run_id: int, phase: str) -> str | None:
    """Log de la phase lu depuis ``logs/pipeline.log``, ou ``None`` si le fichier
    est absent (``LOG_TO_FILE`` désactivé) ou si la section est introuvable."""
    if not PIPELINE_LOG.exists():
        return None
    try:
        text = PIPELINE_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return slice_phase_log(text, run_id, phase)
