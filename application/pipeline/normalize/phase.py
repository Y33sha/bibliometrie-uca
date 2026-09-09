"""Orchestrateur de la phase `normalize` : normalisation staging → tables sources.

Enchaîne, dans l'ordre de priorité des sources (la plus fiable en premier, pour que les suivantes n'écrasent pas les métadonnées déjà posées) :

1. la normalisation de chaque source retenue (staging → `source_publications`, adresses, ORCID/IdRef pour HAL) ;
2. la suppression des `source_publications` dont le staging porte `disappeared_at` ;
3. le nettoyage des identités d'auteur orphelines (la normalisation réassigne des signatures et la suppression précédente en retire, laissant des `author_identifying_keys` que plus aucune signature ne référence) ;
4. le `VACUUM` du staging (`raw_data` vidé après normalisation) — `VACUUM FULL` en mode full, simple sinon.

Les runners par source, la suppression, le nettoyage et le VACUUM (maintenance physique) sont injectés par le composition-root ; ici, la séquence, la sélection/l'ordre des sources et l'assemblage des métriques.
"""

import logging
import time
from collections.abc import Callable
from typing import cast

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODES
from application.pipeline.progression import attente

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
    prune_disappeared: Callable[[], int],
    cleanup_orphan_identities: Callable[[], None],
    vacuum_staging: VacuumStaging,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Normalise les sources retenues (dans l'ordre de priorité), retire les documents disparus, nettoie puis VACUUM le staging."""
    etape(logger, "Normalisation")
    rows = [normalize_one(source) for source in ordered_sources if source in sources]

    disparues = prune_disappeared()

    etape(logger, "Maintenance des tables")
    t0 = time.perf_counter()
    with attente(f"{DERNIERE_BRANCHE}en cours", logger) as ligne:
        cleanup_orphan_identities()
        vacuum_staging(MODES[mode].vacuum_full)
        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")

    metrics = PhaseMetrics()
    normalises = sum(cast("int", row["processed"]) for row in rows)
    metrics.add(total=normalises)
    metrics.resume = f"{accord(normalises, 'document normalisé', 'documents normalisés')}"
    metrics.details["table"] = {"rows": rows}
    metrics.details["disappeared_pruned"] = disparues
    return metrics
