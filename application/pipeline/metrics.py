"""Métriques retournées par les phases du pipeline.

Chaque `run(...)` de phase retourne un `PhaseMetrics`. L'orchestrateur
(`run_pipeline.py`) mesure la durée et agrège les métriques par phase.
La consommation (rapport, dashboard) est traitée dans Volet B du chantier
`CODE_observabilite-robustesse-pipeline.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from application.ports.pipeline.phase_executions import PhaseMetricsPayload, Signal


@dataclass
class PhaseMetrics:
    """Compteurs d'une exécution de phase pipeline.

    `new`, `updated`, `unchanged`, `errors` couvrent les cas standards.
    `updated` = contenu réécrit (hash changé) ; `unchanged` = re-vu à contenu
    identique (seul `last_seen_at` bumpé). `extras` accueille les compteurs
    spécifiques à une phase quand ils ne rentrent pas dans le cadre générique :
    `already_complete` pour `refetch_truncated`, `tagged` pour `extract_hal`,
    `not_found` pour les fetchers HAL, etc.

    `total` (items traités) est **dérivé** : `max(seen, new+updated+unchanged)`.
    Il vaut le dénominateur explicite `seen` (items interrogés/vus, alimenté par
    `add(total=…)`) dès qu'il dépasse les catégorisés, sinon la somme catégorisée.
    Garanti `≥ new+updated+unchanged` par construction — impossible de le
    désynchroniser comme le faisait un compteur saisi à la main (un extracteur qui
    catégorise sans incrémenter le total fausserait l'affichage).

    `details` porte les indicateurs sur-mesure d'observabilité (conventions
    `summary`, `table`, lues par l'interface) et `signals` le motif d'un statut
    dégradé (source coupée après une série de 429/5xx…), qui fait passer le point de
    la phase en ambre et s'affiche au drill-down : tous deux remontés à
    l'orchestrateur pour la capture par phase, sans rôle dans les compteurs.
    """

    new: int = 0
    updated: int = 0
    unchanged: int = 0
    seen: int = 0
    errors: int = 0
    extras: dict[str, int] = field(default_factory=dict)
    details: dict[str, object] = field(default_factory=dict)
    signals: list[Signal] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Items traités : dénominateur explicite `seen`, ou somme catégorisée si plus grande."""
        return max(self.seen, self.new + self.updated + self.unchanged)

    def add(
        self,
        *,
        new: int = 0,
        updated: int = 0,
        unchanged: int = 0,
        total: int = 0,
        errors: int = 0,
        **extras: int,
    ) -> None:
        """Incrémente les compteurs en place. `total=` alimente le dénominateur `seen`."""
        self.new += new
        self.updated += updated
        self.unchanged += unchanged
        self.seen += total
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
        self.unchanged += other.unchanged
        self.seen += other.seen
        self.errors += other.errors
        for k, v in other.extras.items():
            self.extras[k] = self.extras.get(k, 0) + v
        self.details.update(other.details)
        self.signals.extend(other.signals)

    def to_payload(self, duration_s: float) -> PhaseMetricsPayload:
        """Sérialise les compteurs et la durée d'exécution vers le payload de transport
        (`application.ports.pipeline.phase_executions`), persisté par l'observabilité."""
        return {
            "new": self.new,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "total": self.total,
            "errors": self.errors,
            "extras": dict(self.extras),
            "duration_s": duration_s,
        }

    def as_summary(self) -> str:
        """Une-ligne lisible pour les logs ('10 new, 5 updated' / '...')."""
        parts: list[str] = []
        if self.new:
            parts.append(f"{self.new} new")
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.unchanged:
            parts.append(f"{self.unchanged} unchanged")
        if self.errors:
            parts.append(f"{self.errors} errors")
        for k, v in self.extras.items():
            if v:
                parts.append(f"{v} {k}")
        if self.total and not parts:
            parts.append(f"{self.total} total")
        return ", ".join(parts) if parts else "no-op"
