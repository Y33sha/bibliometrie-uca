"""Modèles Pydantic pour la page admin pipeline (statut en cours + log par phase)."""

from pydantic import BaseModel


class PipelineStatus(BaseModel):
    """État du pipeline en cours (lu depuis logs/status.json).

    L'objet n'est rendu que lorsqu'un run tourne : sa seule présence dit « en cours », inutile de porter un drapeau qui vaudrait toujours vrai.
    """

    mode: str
    phase: str
    started_at: str
    phase_started_at: str
    phases_done: int
    phases_total: int


class PipelinePhaseLog(BaseModel):
    """Log d'une phase, découpé depuis logs/pipeline.log.

    `available` est faux quand le fichier est absent (LOG_TO_FILE désactivé) ou quand la section de la phase est introuvable (log purgé) ; `content` est alors vide.

    `content` porte la fin de la section, la plus parlante sur la façon dont la phase s'est terminée. `omitted_lines` compte celles qui la précèdent sans être rendues, et vaut zéro quand la section tient entière : une troncature s'annonce, elle ne se devine pas.
    """

    available: bool
    content: str
    omitted_lines: int = 0
