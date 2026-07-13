"""Marqueurs de log délimitant runs et phases dans `logs/pipeline.log`.

`run_pipeline` les émet dans ses messages, `phase_logs` les parse pour découper le log par phase.
"""

RUN_MARKER = "Run pipeline #"
PHASE_MARKER = "PHASE : "
RUN_END_MARKER = "PIPELINE TERMINÉ"
