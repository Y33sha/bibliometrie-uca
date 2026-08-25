"""Extraction du log d'une phase depuis `logs/pipeline.log`.

L'orchestrateur écrit ses logs dans un fichier unique et append-only (`logs/pipeline.log` via `setup_logger` quand `LOG_TO_FILE=true`). Les runs et les phases y sont bornés par des marqueurs textuels stables, émis par `run_pipeline.py` :

- début de run : `Run pipeline #<run_id>` ;
- début de phase : `PHASE : <nom>` ;
- fin de run : `PIPELINE TERMINÉ`.

Servir le log d'une phase revient à découper la section correspondante du fichier. Le découpage se fait sur les marqueurs (présents quel que soit `LOG_FORMAT`, texte ou JSON — ils vivent dans le message), en un seul passage sur les lignes et sans jamais tenir en mémoire plus que la section rendue : le fichier grossit sans borne, la lecture ne le suit pas.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import PHASE_MARKER, RUN_END_MARKER, RUN_MARKER

PIPELINE_LOG = PROJECT_ROOT / "logs" / "pipeline.log"

# Nombre de lignes rendues au plus, prises à la fin de la section : la fin d'une phase dit
# comment elle s'est terminée, ce qu'on vient chercher. Au-delà, les lignes antérieures sont
# comptées et annoncées, jamais escamotées en silence.
MAX_PHASE_LOG_LINES = 2000


@dataclass(frozen=True)
class PhaseLogExcerpt:
    """Fin de la section d'une phase, et le nombre de lignes qui la précèdent sans être rendues."""

    content: str
    omitted_lines: int


def slice_phase_log(
    lines: Iterable[str],
    run_id: int,
    phase: str,
    *,
    max_lines: int = MAX_PHASE_LOG_LINES,
) -> PhaseLogExcerpt | None:
    """Section du log correspondant à `phase` dans le run `run_id`, lue en un passage sur `lines`.

    Renvoie `None` si le run ou la phase ne figure pas dans les lignes (log purgé, run antérieur au suivi, phase non jouée). La section court du marqueur `PHASE : <phase>` jusqu'au prochain début de phase, début de run ou fin de run (bornes exclues) ; pour un run encore en cours, jusqu'à la fin des lignes. Passé `max_lines`, seules les dernières sont rendues, `omitted_lines` portant le compte des autres.
    """
    run_re = re.compile(rf"{re.escape(RUN_MARKER)}{run_id}(?!\d)")
    phase_re = re.compile(rf"{re.escape(PHASE_MARKER)}{re.escape(phase)}\b")

    in_run = False
    kept: deque[str] | None = None
    omitted = 0

    for raw in lines:
        line = raw.rstrip("\n")
        if kept is None:
            if not in_run:
                in_run = bool(run_re.search(line))
            elif phase_re.search(line):
                kept = deque([line], maxlen=max_lines)
            continue
        if PHASE_MARKER in line or RUN_MARKER in line or RUN_END_MARKER in line:
            break
        if len(kept) == max_lines:
            omitted += 1
        kept.append(line)

    if kept is None:
        return None
    return PhaseLogExcerpt(content="\n".join(kept), omitted_lines=omitted)


def read_phase_log(run_id: int, phase: str) -> PhaseLogExcerpt | None:
    """Log de la phase lu depuis `logs/pipeline.log`, ou `None` si le fichier est absent (`LOG_TO_FILE` désactivé) ou si la section est introuvable.

    Le fichier est parcouru ligne à ligne : sa taille ne détermine pas la mémoire consommée.
    """
    if not PIPELINE_LOG.exists():
        return None
    try:
        with PIPELINE_LOG.open(encoding="utf-8", errors="replace") as f:
            return slice_phase_log(f, run_id, phase)
    except OSError:
        return None
