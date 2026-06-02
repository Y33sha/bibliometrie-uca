"""Value objects pour les snapshots de runs pipeline (Phase 2 du chantier observabilité).

Un `RunSnapshot` agrège, pour un run complet du pipeline, à la fois :
- les **observables** post-run (état de la BDD : volumes, orphelins, distributions,
  qualité matching), comparés au dernier snapshot du même mode ;
- les **`PhaseMetrics` par phase** (compteurs d'exécution, durées) ;
- les **métadonnées du run** (durée totale, sources interrogées, phases exécutées).

`Observation` décrit une seule mesure d'observable, avec son delta vs précédent
et un drapeau `suspect` si le delta dépasse un seuil.

Placé en `application/ports/` (zone neutre) parce que ces dataclasses circulent entre
l'implémentation I/O — `infrastructure/observability/pipeline_runs.py` — qui calcule
et persiste, et le hook orchestrateur côté `run_pipeline.py` qui rend le résumé.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TypedDict


class ObservablesPayload(TypedDict):
    """Section `observables` du payload : état de la BDD après le run.

    Quatre familles : volumes (counts entiers), orphelins (counts entiers),
    distributions (ratios par clé), qualité matching (counts entiers).
    """

    volumes: dict[str, int]
    orphans: dict[str, int]
    distributions: dict[str, dict[str, float]]
    matching_quality: dict[str, int]


class PhaseMetricsPayload(TypedDict):
    """Métriques sérialisées d'une phase pipeline.

    Sérialisation JSON-compatible de `application.pipeline.metrics.PhaseMetrics`
    + la durée mesurée par l'orchestrateur.
    """

    new: int
    updated: int
    unchanged: int
    total: int
    errors: int
    extras: dict[str, int]
    duration_s: float


class RunSnapshotPayload(TypedDict):
    """Forme complète du payload JSONB stocké dans `pipeline_run_snapshots`.

    Une vue unifiée d'un run : observables (état après) + métriques par phase
    (exécution) + métadonnées (sources, phases, durée totale).
    """

    observables: ObservablesPayload
    metrics_per_phase: dict[str, PhaseMetricsPayload]
    total_duration_s: float
    sources: list[str]
    phases_run: list[str]


@dataclass(frozen=True)
class Observation:
    key: str
    label: str
    current: float
    previous: float | None
    delta_pct: float | None
    suspect: bool
    threshold_note: str


@dataclass
class RunSnapshot:
    mode: str
    ran_at: datetime.datetime
    previous_snapshot_at: datetime.datetime | None
    current: RunSnapshotPayload
    observations: list[Observation]

    @property
    def suspect_observations(self) -> list[Observation]:
        return [o for o in self.observations if o.suspect]
