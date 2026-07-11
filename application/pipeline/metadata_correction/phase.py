"""Orchestrateur de la phase `metadata_correction` : persistance des corrections de métadonnées sur les `source_publications`.

Trois sous-étapes, chacune dans sa propre transaction, dans cet ordre :

1. **journal_by_doi** — rattache le journal manquant quand le préfixe DOI correspond à un unique journal possible. En premier : le `journal_id` qu'il commit est consommé par l'étape suivante (`journal_type` depuis la colonne vivante), de sorte que la reclassification `doc_type` journal-dépendante a lieu dans le même run, sans feed-forward.
2. **unaire** (per-record) — mapping `doc_type` source→canonique puis règles de correction `effective_metadata`.
3. **cluster** (group-by-DOI) — substitution version→concept DataCite, nullage des DOI erronés ouvrage/chapitre.
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.metadata_correction.correct_by_cluster import run as run_cluster
from application.pipeline.metadata_correction.correct_unary import run as run_unary
from application.pipeline.metadata_correction.journal_by_doi import run as run_journal_by_doi
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.pipeline.transaction import OpenTransaction


def _step[T](
    open_tx: OpenTransaction, label: str, step: Callable[[Connection], T], logger: logging.Logger
) -> T:
    """Exécute une sous-étape dans sa propre transaction, encadrée d'un chronométrage `▶`/`✓`."""
    logger.info("▶ metadata_correction (%s)", label)
    t0 = time.perf_counter()
    with open_tx() as conn:
        result = step(conn)
    logger.info("✓ metadata_correction (%s) terminé en %.1fs", label, time.perf_counter() - t0)
    return result


def run(
    open_tx: OpenTransaction, queries: MetadataCorrectionQueries, logger: logging.Logger
) -> PhaseMetrics:
    """Enchaîne les trois sous-étapes et assemble les métriques de la phase."""
    journal_by_doi = _step(
        open_tx, "journal_by_doi", lambda conn: run_journal_by_doi(conn, queries, logger), logger
    )
    unary = _step(open_tx, "unaire", lambda conn: run_unary(conn, queries, logger), logger)
    cluster = _step(open_tx, "cluster", lambda conn: run_cluster(conn, queries, logger), logger)

    metrics = PhaseMetrics()
    metrics.add(
        total=journal_by_doi.examined + unary.examined + cluster.examined,
        updated=journal_by_doi.attached + unary.corrected + cluster.corrected,
    )
    # Chiffres plats : `{mode}_{examined,corrected}`. Le frontend les arrange en matrice (mode × examinées/corrigées) — pur agencement de présentation.
    metrics.details["summary"] = {
        "journal_by_doi_examined": journal_by_doi.examined,
        "journal_by_doi_corrected": journal_by_doi.attached,
        "unary_examined": unary.examined,
        "unary_corrected": unary.corrected,
        "cluster_examined": cluster.examined,
        "cluster_corrected": cluster.corrected,
    }
    counts = list(unary.rule_counts.items()) + list(cluster.case_counts.items())
    counts.sort(key=lambda kc: kc[1], reverse=True)
    metrics.details["table"] = {"rows": [{"key": key, "count": count} for key, count in counts]}
    return metrics
