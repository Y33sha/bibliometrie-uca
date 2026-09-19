"""Orchestrateur de la phase `metadata_correction` : persistance des corrections de métadonnées sur les `source_publications`.

Deux sous-étapes, chacune dans sa propre transaction, dans cet ordre :

1. **unaire** (per-record) — mapping `doc_type` source→canonique puis règles de correction `effective_metadata`.
2. **cluster** (group-by-DOI) — substitution version→concept DataCite, nullage des DOI erronés ouvrage/chapitre.
"""

import logging
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.metadata_correction.correct_by_cluster import run as run_cluster
from application.pipeline.metadata_correction.correct_unary import run as run_unary
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.pipeline.transaction import OpenTransaction


def _step[T](open_tx: OpenTransaction, step: Callable[[Connection], T]) -> T:
    """Exécute une sous-étape dans sa propre transaction."""
    with open_tx() as conn:
        return step(conn)


def run(
    open_tx: OpenTransaction, queries: MetadataCorrectionQueries, logger: logging.Logger
) -> PhaseMetrics:
    """Enchaîne les deux sous-étapes et assemble les métriques de la phase."""
    unary = _step(open_tx, lambda conn: run_unary(conn, queries, logger))
    cluster = _step(open_tx, lambda conn: run_cluster(conn, queries, logger))

    metrics = PhaseMetrics()
    metrics.add(
        total=unary.examined + cluster.examined,
        updated=unary.corrected + cluster.corrected,
    )
    # Chiffres plats : `{mode}_{examined,corrected}`. Le frontend les arrange en matrice (mode × examinées/corrigées) — pur agencement de présentation.
    metrics.details["summary"] = {
        "unary_examined": unary.examined,
        "unary_corrected": unary.corrected,
        "cluster_examined": cluster.examined,
        "cluster_corrected": cluster.corrected,
    }
    counts = list(unary.rule_counts.items()) + list(cluster.case_counts.items())
    counts.sort(key=lambda kc: kc[1], reverse=True)
    metrics.details["table"] = {"rows": [{"key": key, "count": count} for key, count in counts]}
    # Chaque sous-étape conclut la sienne ; la table d'observabilité garde le détail.
    metrics.resume = ""
    return metrics
