"""Métriques retournées par les phases du pipeline.

Chaque `run(...)` de phase retourne un `PhaseMetrics`. L'orchestrateur
(`run_pipeline.py`) mesure la durée et agrège les métriques par phase.
La consommation (rapport, dashboard) est traitée dans Volet B du chantier
`CODE_observabilite-robustesse-pipeline.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PhaseMetrics:
    """Compteurs d'une exécution de phase pipeline.

    `new`, `updated`, `total`, `errors` couvrent les cas standards
    (insert, update, ignoré, erreur). `extras` accueille les compteurs
    spécifiques à une phase quand ils ne rentrent pas dans le cadre
    générique : `already_complete` pour `refetch_truncated`, `tagged`
    pour `extract_hal`, `not_found` pour les fetchers HAL, etc.
    """

    new: int = 0
    updated: int = 0
    total: int = 0
    errors: int = 0
    extras: dict[str, int] = field(default_factory=dict)

    def add(
        self,
        *,
        new: int = 0,
        updated: int = 0,
        total: int = 0,
        errors: int = 0,
        **extras: int,
    ) -> None:
        """Incrémente les compteurs en place."""
        self.new += new
        self.updated += updated
        self.total += total
        self.errors += errors
        for k, v in extras.items():
            self.extras[k] = self.extras.get(k, 0) + v

    def merge(self, other: PhaseMetrics) -> None:
        """Agrège les compteurs d'un autre `PhaseMetrics` en place.

        Utilisé par les phases qui chaînent plusieurs sous-helpers (ex:
        `phase_extract` accumule les 5 extracteurs sources).
        """
        self.new += other.new
        self.updated += other.updated
        self.total += other.total
        self.errors += other.errors
        for k, v in other.extras.items():
            self.extras[k] = self.extras.get(k, 0) + v

    def as_summary(self) -> str:
        """Une-ligne lisible pour les logs ('10 new, 5 updated' / '...')."""
        parts: list[str] = []
        if self.new:
            parts.append(f"{self.new} new")
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.errors:
            parts.append(f"{self.errors} errors")
        for k, v in self.extras.items():
            if v:
                parts.append(f"{v} {k}")
        if self.total and not parts:
            parts.append(f"{self.total} total")
        return ", ".join(parts) if parts else "no-op"
