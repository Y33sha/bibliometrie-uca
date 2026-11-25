"""Phases aux exécutions de tâches remplacées, pour les tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from pipeline.graph import Phase, Step, Task, TaskRun


def with_runs(phase: Phase, runs: Mapping[str, TaskRun]) -> Phase:
    """Renvoie `phase`, l'exécution de chaque tâche nommée dans `runs` remplacée. Les étapes et leurs sections restent en place."""

    def replaced(child: Step | Task) -> Step | Task:
        if isinstance(child, Step):
            return dataclasses.replace(child, children=tuple(map(replaced, child.children)))
        return dataclasses.replace(child, run=runs.get(child.name, child.run))

    return dataclasses.replace(phase, children=tuple(map(replaced, phase.children)))
