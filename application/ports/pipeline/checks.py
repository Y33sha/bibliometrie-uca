"""Value objects pour les checks post-pipeline (Volet A du chantier observabilité).

Une `Observation` = un observable mesuré à un instant T, comparé à sa valeur dans
le dernier snapshot du même mode. Un `CheckReport` agrège toutes les observations
d'un run. `ObservablesPayload` décrit la forme stockée dans
`pipeline_check_snapshots.payload` (JSONB).

Placé en `application/ports/` (zone neutre) parce que ces dataclasses circulent entre
l'implémentation I/O — `infrastructure/observability/pipeline_checks.py` — qui calcule
et persiste, et le hook orchestrateur côté `run_pipeline.py` qui rend le résumé.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TypedDict


class ObservablesPayload(TypedDict):
    """Forme du payload JSONB stocké dans `pipeline_check_snapshots`.

    Quatre familles : volumes (counts entiers), orphelins (counts entiers),
    distributions (ratios par clé), qualité matching (counts entiers).
    """

    volumes: dict[str, int]
    orphans: dict[str, int]
    distributions: dict[str, dict[str, float]]
    matching_quality: dict[str, int]


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
class CheckReport:
    mode: str
    ran_at: datetime.datetime
    previous_snapshot_at: datetime.datetime | None
    current: ObservablesPayload
    observations: list[Observation]

    @property
    def suspect_observations(self) -> list[Observation]:
        return [o for o in self.observations if o.suspect]
