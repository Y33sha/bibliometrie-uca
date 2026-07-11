"""Orchestrateur de la phase `normalize` : normalisation staging → tables sources.

Enchaîne, dans l'ordre de priorité des sources (la plus fiable en premier, pour que les suivantes n'écrasent pas les métadonnées déjà posées) :

1. la normalisation de chaque source retenue (staging → `source_publications`, adresses, ORCID/IdRef pour HAL) ;
2. le nettoyage des identités d'auteur orphelines (la normalisation a pu réassigner des signatures, laissant des `author_identifying_keys` que plus aucune signature ne référence) ;
3. le `VACUUM` du staging (`raw_data` vidé après normalisation) — `VACUUM FULL` en mode full, simple sinon.

Les runners par source, le nettoyage et le VACUUM (maintenance physique) sont injectés par le composition-root ; ici, la séquence, la sélection/l'ordre des sources et l'assemblage des métriques.
"""

import logging
import time
from collections.abc import Callable
from typing import cast

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODES

NormalizeOne = Callable[[str], dict[str, object]]
"""Normalise une source (connexion + normaliseur câblé) et rend sa ligne d'observabilité."""
VacuumStaging = Callable[[bool], None]
"""`VACUUM` du staging (maintenance physique, autocommit) ; `full=True` réécrit la table."""


def run(
    *,
    sources: set[str],
    mode: str,
    ordered_sources: list[str],
    normalize_one: NormalizeOne,
    cleanup_orphan_identities: Callable[[], None],
    vacuum_staging: VacuumStaging,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Normalise les sources retenues (dans l'ordre de priorité), nettoie puis VACUUM le staging."""
    rows = [normalize_one(source) for source in ordered_sources if source in sources]

    cleanup_orphan_identities()

    vacuum_full = MODES[mode].vacuum_full
    label = "VACUUM FULL" if vacuum_full else "VACUUM"
    logger.info("▶ %s staging…", label)
    t0 = time.perf_counter()
    vacuum_staging(vacuum_full)
    logger.info("✓ %s staging terminé en %.1fs", label, time.perf_counter() - t0)

    metrics = PhaseMetrics()
    metrics.add(total=sum(cast("int", row["processed"]) for row in rows))
    metrics.details["table"] = {"rows": rows}
    return metrics
