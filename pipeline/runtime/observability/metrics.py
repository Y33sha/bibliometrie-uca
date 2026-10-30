"""Compteurs que renvoie chaque phase du pipeline. L'orchestrateur en mesure la durée et les enregistre (`to_payload`)."""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.pipeline_runs import PhaseMetricsPayload, Signal
from pipeline.runtime.observability.log_format import inflect

EXTRA_LABELS: dict[str, str | tuple[str, str]] = {
    "already_complete": "déjà complet",
    "conflicts": "conflit",
    "disappeared": "disparu",
    "fetched": "récupéré",
    "issn_conflicts": ("conflit entre publications", "conflits entre publications"),
    "issn_corrected": ("ISSN corrigé", "ISSN corrigés"),
    "issn_discarded": (
        "ISSN d'une autre publication écarté",
        "ISSN d'autres publications écartés",
    ),
    "issn_from_documents": ("ISSN repris d'un enregistrement", "ISSN repris d'enregistrements"),
    "issn_set_aside": ("ISSN mis de côté", "ISSN mis de côté"),
    "serial_doi_namespaces": ("espace de noms DOI de revue", "espaces de noms DOI de revues"),
    "serials_deleted": ("revue vide supprimée", "revues vides supprimées"),
    "serials_merged": ("revue fusionnée", "revues fusionnées"),
    "serials_typed_journal": ("entrée typée revue", "entrées typées revues"),
    "serials_typed_proceedings": (
        "revue typée recueil d'actes",
        "revues typées recueils d'actes",
    ),
    "matched": "retrouvé",
    "monograph_collection_conflicts": (
        "monographie à plusieurs collections possibles",
        "monographies à plusieurs collections possibles",
    ),
    "monograph_series": ("série sans ISSN de monographies", "séries sans ISSN de monographies"),
    "monographs_deleted": ("monographie vide supprimée", "monographies vides supprimées"),
    "monographs_linked": (
        "monographie rattachée à sa collection",
        "monographies rattachées à leur collection",
    ),
    "monographs_merged": ("monographie fusionnée", "monographies fusionnées"),
    "monographs_to_books": ("volume d'actes retypé livre", "volumes d'actes retypés livres"),
    "monographs_to_proceedings": (
        "livre retypé volume d'actes",
        "livres retypés volumes d'actes",
    ),
    "no_publisher": ("sans éditeur", "sans éditeur"),
    "not_found": "introuvable",
    "publisher_created": ("éditeur créé", "éditeurs créés"),
    "publisher_matched": ("éditeur retrouvé", "éditeurs retrouvés"),
    "publishers_deleted": ("éditeur vide supprimé", "éditeurs vides supprimés"),
    "publishers_merged": ("éditeur fusionné", "éditeurs fusionnés"),
    "resolved": "résolu",
    "series_titled": (
        "série renommée d'après son titre de référence",
        "séries renommées d'après leur titre de référence",
    ),
    "skipped": "sauté",
    "sudoc_found": ("présente dans le Sudoc", "présentes dans le Sudoc"),
    "unknown_to_doi_org": ("DOI inconnu de doi.org", "DOI inconnus de doi.org"),
    "unmatched": "non retrouvé",
    "unresolved": "non résolu",
}
"""Libellés des compteurs propres à une phase, au singulier. Un couple donne les formes que le `s` final ne donne pas."""


@dataclass
class PhaseMetrics:
    """Compteurs d'une exécution de phase.

    `updated` : contenu réécrit ; `unchanged` : revu à contenu identique. `extras` : compteurs propres à la phase (`EXTRA_LABELS`). `details` : indicateurs que l'interface affiche (`summary`, `table`). `signals` : motifs d'un statut dégradé, comme une source coupée.
    """

    new: int = 0
    updated: int = 0
    unchanged: int = 0
    seen: int = 0
    errors: int = 0
    extras: dict[str, int] = field(default_factory=dict)
    details: dict[str, object] = field(default_factory=dict)
    signals: list[Signal] = field(default_factory=list)
    report: str | None = field(default=None, compare=False)
    """Ligne de bilan de la tâche, dans les mots de la tâche. `as_summary()` prend le relais à défaut.

    Hors comparaison : deux relevés portant les mêmes compteurs sont égaux, quels que soient les mots qui les présentent.
    """
    duration_s: float | None = field(default=None, compare=False)
    """Durée d'une tâche en secondes, mesurée par l'exécuteur ; `merge` l'ignore."""

    @property
    def total(self) -> int:
        """Éléments traités : `seen`, ou la somme de `new`, `updated` et `unchanged` si elle est plus grande."""
        return max(self.seen, self.new + self.updated + self.unchanged)

    def add(
        self,
        *,
        new: int = 0,
        updated: int = 0,
        unchanged: int = 0,
        seen: int = 0,
        errors: int = 0,
        **extras: int,
    ) -> None:
        """Incrémente les compteurs en place."""
        self.new += new
        self.updated += updated
        self.unchanged += unchanged
        self.seen += seen
        self.errors += errors
        for k, v in extras.items():
            self.extras[k] = self.extras.get(k, 0) + v

    def merge(self, other: PhaseMetrics) -> None:
        """Ajoute en place les compteurs, détails et signaux de `other`."""
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
        """Forme JSON des compteurs, durée comprise (`domain.pipeline_runs.PhaseMetricsPayload`)."""
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
        """Ligne de journal des compteurs (« 10 nouveaux, 5 mis à jour »)."""
        # Les clés d'`extras` sont celles des runs enregistrés, que lit l'interface : la traduction se fait à l'affichage.
        parts: list[str] = []
        if self.new:
            parts.append(f"{self.new} {inflect(self.new, 'nouveau', 'nouveaux')}")
        if self.updated:
            parts.append(f"{self.updated} mis à jour")
        if self.unchanged:
            parts.append(f"{self.unchanged} {inflect(self.unchanged, 'inchangé')}")
        if self.errors:
            parts.append(f"{self.errors} {inflect(self.errors, 'erreur')}")
        for k, v in self.extras.items():
            if v:
                label = EXTRA_LABELS.get(k, (k, k))
                singular, plural = label if isinstance(label, tuple) else (label, None)
                parts.append(f"{v} {inflect(v, singular, plural)}")
        if self.total and not parts:
            parts.append(f"{self.total} au total")
        return ", ".join(parts) if parts else "rien à faire"
